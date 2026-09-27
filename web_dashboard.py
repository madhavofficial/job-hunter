"""Interactive Web Dashboard & 1-Click Application Server for Job Hunter.

Provides a clean, local web interface where you can:
- View categorized job matches (Fresh Today, Tier 1 AI Startups, Tier 2 Enterprises)
- Search, filter, and sort roles in real time (Match %, Newest, Company A-Z)
- Quick View full job descriptions, extracted skills, and AI match rationale in a modal
- Click [⚡ 1-Click Apply & Tailor] to generate an ATS Single-Page Resume PDF, open the application URL, and track status
- Click [✕ Dismiss] with instant [Undo] protection
- Track applied jobs with direct status portal links (Workday, Oracle Cloud, Greenhouse, etc.)
- Ingest custom job postings via interactive dialog or paste raw JD
- Click [🧹 Clean Stale Jobs] to auto-archive older unapplied listings
"""

import http.server
import json
import os
import re
import socketserver
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from datetime import datetime, timedelta

import db
import tailor
import profiles
from notion_sync import derive_status_portal_url, map_platform
from screening import classify_company_tier, is_job_truly_remote
from quality import assess_listing_quality, quality_gate, weighted_match_score

PORT = 8765
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TAILORED_DIR = os.path.abspath(os.path.join(BASE_DIR, "tailored"))


def is_safe_tailored_path(path: str) -> bool:
    """Validate that path is strictly contained within the tailored directory."""
    if not path:
        return False
    try:
        abs_path = os.path.abspath(path)
        return (
            os.path.commonpath([TAILORED_DIR, abs_path]) == TAILORED_DIR
            and abs_path != TAILORED_DIR
        )
    except (ValueError, Exception):
        return False


import uuid

# --- Async apply task tracking ---
# Maps task_id -> {"status": "pending"|"done"|"confirmed"|"error", "result": ..., "error": ...}
_apply_tasks: dict = {}
_apply_tasks_lock = threading.Lock()


def _run_tailor_worker(tid: str, jid: str, job_row: dict, profile_name: str = "madhav"):
    """Tailor materials and open the listing without changing application status."""
    try:
        profile_obj = profiles.get_profile(profile_name)
        job_row = dict(job_row) if job_row is not None else {}
        existing_pdf = job_row.get("tailored_resume_pdf_path")
        if not existing_pdf:
            try:
                conn = db.get_db_connection()
                cur = conn.cursor()
                cur.execute("SELECT tailored_resume_path, tailored_resume_pdf_path FROM jobs WHERE job_id = ?", (jid,))
                db_row = cur.fetchone()
                conn.close()
                if db_row and db_row["tailored_resume_pdf_path"]:
                    existing_pdf = db_row["tailored_resume_pdf_path"]
            except Exception:
                pass

        # Ensure existing PDF belongs to requested profile before reusing
        if existing_pdf and os.path.exists(existing_pdf) and (profile_obj.file_prefix in os.path.basename(existing_pdf)):
            resume_pdf_path = existing_pdf
            resume_path = existing_pdf.replace(".pdf", ".md")
            materials = (resume_path, resume_pdf_path)
        else:
            materials = tailor.tailor_materials(jid, profile_name=profile_name)

        if not materials:
            with _apply_tasks_lock:
                _apply_tasks[tid] = {"status": "error", "result": None, "error": "Failed to tailor materials"}
            return
        resume_path, resume_pdf_path = materials[0], materials[1]
        target_url = job_row.get("job_url_direct") or job_row.get("job_url")
        if target_url and target_url.startswith("http"):
            try:
                webbrowser.open(target_url)
            except Exception:
                pass
        if resume_pdf_path and os.path.exists(resume_pdf_path) and sys.platform == "darwin":
            try:
                subprocess.run(["open", "-R", resume_pdf_path], check=False)
            except Exception:
                pass
        with _apply_tasks_lock:
            _apply_tasks[tid] = {
                "status": "done",
                "result": {
                    "job_id": jid,
                    "resume_path": resume_path,
                    "resume_pdf_path": resume_pdf_path,
                    "url": target_url,
                    "title": job_row.get("title", ""),
                    "company": job_row.get("company", ""),
                },
                "error": None,
            }
    except Exception as e:
        with _apply_tasks_lock:
            _apply_tasks[tid] = {"status": "error", "result": None, "error": str(e)}


def finalize_application(task_id: str, job_id: str, outcome: str) -> dict:
    """Apply the user's Y/S/E confirmation to the database exactly once."""
    normalized = (outcome or "").strip().lower()
    if normalized not in {"applied", "skipped", "expired"}:
        raise ValueError("Outcome must be applied, skipped, or expired")

    with _apply_tasks_lock:
        task = _apply_tasks.get(task_id)
    if not task or task.get("status") != "done" or not task.get("result"):
        raise ValueError("Application task is not ready for confirmation")
    if task["result"].get("job_id") != job_id:
        raise ValueError("Application task does not match this job")

    if normalized == "applied":
        db.mark_as_applied(
            job_id,
            task["result"].get("resume_path"),
            None,
            task["result"].get("resume_pdf_path"),
            None,
        )
    elif normalized == "expired":
        db.mark_as_rejected(job_id)
    else:
        db.mark_as_shortlisted(job_id)

    with _apply_tasks_lock:
        task["status"] = "confirmed"
        task["result"]["application_status"] = normalized
    return {"job_id": job_id, "application_status": normalized}


def get_dashboard_data():
    db.init_db()
    conn = db.get_db_connection()
    cursor = conn.cursor()

    # Query all shortlisted jobs
    cursor.execute("""
    SELECT job_id, site, job_url, job_url_direct, title, company, location,
           date_posted, job_type, is_remote, skills, score, evidence,
           matching_notes, tailored_resume_pdf_path, created_at, status, description,
           recommendation_status, role_fit_score, company_quality_score,
           evidence_quality_score, freshness_score, directness_score, match_components
    FROM jobs
    WHERE status = 'shortlisted'
    ORDER BY score DESC, created_at DESC
    """)
    all_shortlisted = [dict(r) for r in cursor.fetchall()]

    # Query the applied jobs shown in the tracker
    cursor.execute("""
    SELECT job_id, site, job_url, job_url_direct, title, company, location, date_posted, score,
           tailored_resume_pdf_path, created_at, status, description
    FROM jobs
    WHERE status = 'applied'
    ORDER BY created_at DESC LIMIT 100
    """)
    applied = [dict(r) for r in cursor.fetchall()]
    cursor.execute("SELECT COUNT(*) FROM jobs WHERE status = 'applied'")
    total_applied = cursor.fetchone()[0]

    # Total counts
    cursor.execute("SELECT COUNT(*) FROM jobs WHERE status = 'rejected'")
    total_rejected = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM jobs WHERE status = 'scraped'")
    total_scraped = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM jobs WHERE created_at LIKE ?", (f"{datetime.now().strftime('%Y-%m-%d')}%",))
    total_discovered_today = cursor.fetchone()[0]
    conn.close()

    # Enrich all shortlisted roles. Unverified roles remain searchable in the
    # discovery pool but are excluded from Top Matches.
    valid_shortlisted = []
    for j in all_shortlisted:
        tier = classify_company_tier(j["company"])
        j["tier"] = tier
        j["apply_url"] = j["job_url_direct"] or j["job_url"]
        j["is_remote_verified"] = is_job_truly_remote(j)
        j["quality"] = assess_listing_quality(j, tier)
        j["quality_passes"], j["quality_reason"] = quality_gate(j, tier, j["quality"])
        j["recommended"] = (j.get("recommendation_status") == "recommended")
        role_fit = j.get("role_fit_score") or j.get("score") or 0
        j["score"], _ = weighted_match_score(role_fit, j["quality"])
        plat = map_platform(j["apply_url"], j.get("site", ""), j.get("company", ""))
        j["platform"] = plat
        j["status_portal_url"] = derive_status_portal_url(j["apply_url"], plat, j.get("company", ""), j.get("job_id", ""))
        valid_shortlisted.append(j)

    # Ensure all category slices are strictly ordered by descending weighted match score
    valid_shortlisted.sort(key=lambda j: (j.get("score") or 0, j.get("created_at") or ""), reverse=True)

    # Enrich applied jobs with platform & status tracking portal
    for j in applied:
        j["apply_url"] = j["job_url_direct"] or j["job_url"]
        plat = map_platform(j["apply_url"], j.get("site", ""), j.get("company", ""))
        j["platform"] = plat
        j["status_portal_url"] = derive_status_portal_url(j["apply_url"], plat, j.get("company", ""), j.get("job_id", ""))

    # Calculate 48h Freshness cutoff & today's date
    cutoff_48h = (datetime.now() - timedelta(hours=48)).strftime("%Y-%m-%d %H:%M:%S")
    cutoff_7d = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    today_str = datetime.now().strftime("%Y-%m-%d")

    today_jobs = [j for j in valid_shortlisted if (j.get("created_at") or "").startswith(today_str)]
    fresh_jobs = [j for j in valid_shortlisted if (j.get("created_at") or "") >= cutoff_48h]
    remote_jobs = [j for j in valid_shortlisted if j["is_remote_verified"]]
    
    big_tech_jobs = [j for j in valid_shortlisted if "Big Tech" in j["tier"]]
    unicorn_jobs = [j for j in valid_shortlisted if "Unicorn" in j["tier"]]
    startup_jobs = [j for j in valid_shortlisted if "Startup" in j["tier"]]
    it_services_jobs = [j for j in valid_shortlisted if "IT Services" in j["tier"]]

    tier1_jobs = [j for j in valid_shortlisted if ("Startup" in j["tier"] or "Unicorn" in j["tier"] or "Big Tech" in j["tier"])]
    tier2_jobs = it_services_jobs

    recommended_jobs = [j for j in valid_shortlisted if j["recommended"]]
    discovery_jobs = [j for j in valid_shortlisted if not j["recommended"]]
    older_jobs = [j for j in valid_shortlisted if (j.get("created_at") or "") < cutoff_7d]

    return {
        "stats": {
            "total_shortlisted": len(valid_shortlisted),
            "recommended_count": len(recommended_jobs),
            "discovered_today": len(today_jobs),
            "total_discovered_today": total_discovered_today,
            "fresh_48h": len(fresh_jobs),
            "remote_count": len(remote_jobs),
            "big_tech_count": len(big_tech_jobs),
            "unicorn_count": len(unicorn_jobs),
            "startup_count": len(startup_jobs),
            "it_services_count": len(it_services_jobs),
            "tier1_count": len(tier1_jobs),
            "tier2_count": len(tier2_jobs),
            "total_applied": total_applied,
            "total_rejected": total_rejected,
            "pending_matching": total_scraped,
            "older_count": len(older_jobs),
        },
        "today_jobs": today_jobs,
        "fresh_jobs": fresh_jobs[:40],
        "recommended_jobs": recommended_jobs[:40],
        "discovery_jobs": discovery_jobs,
        "remote_jobs": remote_jobs[:50],
        "big_tech_jobs": big_tech_jobs[:40],
        "unicorn_jobs": unicorn_jobs[:40],
        "startup_jobs": startup_jobs[:50],
        "it_services_jobs": it_services_jobs[:35],
        "tier1_jobs": tier1_jobs[:50],
        "tier2_jobs": tier2_jobs[:35],
        "all_shortlisted": valid_shortlisted,
        "applied_jobs": applied,
    }


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Job Hunter — Executive Career Operations Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        * { font-family: 'Inter', system-ui, -apple-system, BlinkMacSystemFont, sans-serif; }
        .font-mono { font-family: 'JetBrains Mono', monospace; }
        .gradient-card { background: linear-gradient(135deg, #161824 0%, #10121a 100%); }
        .tab-btn.active { border-bottom: 2px solid #38bdf8; color: #38bdf8; font-weight: 600; }
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: #0b0c10; }
        ::-webkit-scrollbar-thumb { background: #222638; border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: #323852; }
        dialog::backdrop {
            background: rgba(4, 6, 11, 0.85);
            backdrop-filter: blur(12px);
        }
    </style>
</head>
<body class="bg-[#0b0c10] text-slate-100 min-h-screen font-sans antialiased selection:bg-sky-500/30 selection:text-sky-200">
    <!-- Header -->
    <header class="border-b border-[#1c1f2e] bg-[#0f1118]/80 backdrop-blur sticky top-0 z-40">
        <div class="max-w-7xl mx-auto px-4 py-3 sm:px-6 flex items-center justify-between">
            <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-sky-500 via-indigo-500 to-teal-400 p-[1px] shadow-lg shadow-sky-500/20">
                    <div class="w-full h-full bg-[#0b0c10] rounded-[11px] flex items-center justify-center">
                        <i class="fa-solid fa-briefcase text-sky-400 text-base"></i>
                    </div>
                </div>
                <div>
                    <h1 class="text-base font-bold tracking-tight text-white flex items-center gap-2">
                        Job Hunter Operations
                        <span class="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">Live</span>
                    </h1>
                    <p class="text-xs text-slate-400">Autonomous Screening, ATS PDF Tailoring & Application Hub</p>
                </div>
            </div>
            <div class="flex items-center gap-2">
                <div class="flex items-center gap-1.5 bg-[#151824] border border-[#24283b] rounded-xl px-2.5 py-1.5 text-xs shadow-sm">
                    <i class="fa-solid fa-user-gear text-sky-400"></i>
                    <span class="text-slate-400 text-[11px] font-medium hidden md:inline">Profile:</span>
                    <select id="activeProfileSelect" onchange="onProfileChange(this.value)" class="bg-transparent text-slate-200 text-xs font-semibold focus:outline-none cursor-pointer">
                        <option value="madhav" class="bg-[#12141d] text-slate-200">Madhav Jayam</option>
                        <option value="mahika" class="bg-[#12141d] text-slate-200">Mahika Neranjen</option>
                    </select>
                </div>
                <button onclick="openCustomJobModal()" class="px-3.5 py-1.5 text-xs font-semibold bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-400 hover:to-teal-500 text-white rounded-xl shadow-sm shadow-emerald-500/20 flex items-center gap-1.5 transition">
                    <i class="fa-solid fa-plus"></i> Add Custom Link
                </button>
                <button onclick="archiveStaleJobs()" class="px-3 py-1.5 text-xs font-medium bg-[#151824] hover:bg-[#1c2030] text-slate-300 rounded-xl border border-[#24283b] flex items-center gap-1.5 transition">
                    <i class="fa-solid fa-broom text-amber-400"></i> Clear Stale (>7d)
                </button>
                <button onclick="fetchJobs()" class="px-3 py-1.5 text-xs font-medium bg-[#151824] hover:bg-[#1c2030] text-sky-400 hover:text-sky-300 rounded-xl border border-[#24283b] shadow-sm flex items-center gap-1.5 transition">
                    <i class="fa-solid fa-rotate"></i> Refresh
                </button>
            </div>
        </div>
    </header>

    <!-- Main Container -->
    <main class="max-w-7xl mx-auto px-4 py-6 sm:px-6 space-y-6">
        <!-- Metrics Ribbon -->
        <div class="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3" id="stats-ribbon">
            <div onclick="switchTab('today')" class="cursor-pointer bg-[#12141d] border border-emerald-500/20 hover:border-emerald-500/50 transition rounded-2xl p-4 flex items-center gap-3.5 shadow-sm group">
                <div class="w-11 h-11 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 text-lg group-hover:scale-105 transition">
                    <i class="fa-solid fa-calendar-day"></i>
                </div>
                <div>
                    <div class="text-2xl font-extrabold text-white tracking-tight" id="stat-discovered-today">0</div>
                    <div class="text-[11px] font-medium text-emerald-400 flex items-center gap-1">Discovered Today <i class="fa-solid fa-arrow-right text-[9px] opacity-0 group-hover:opacity-100 transition"></i></div>
                </div>
            </div>
            <div class="bg-[#12141d] border border-[#1e2233] hover:border-[#2b3047] transition rounded-2xl p-4 flex items-center gap-3.5 shadow-sm group">
                <div class="w-11 h-11 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400 text-lg group-hover:scale-105 transition">
                    <i class="fa-solid fa-fire-flame-curved"></i>
                </div>
                <div>
                    <div class="text-2xl font-extrabold text-white tracking-tight" id="stat-fresh">0</div>
                    <div class="text-[11px] font-medium text-slate-400">Fresh (Past 48h)</div>
                </div>
            </div>
            <div class="bg-[#12141d] border border-[#1e2233] hover:border-[#2b3047] transition rounded-2xl p-4 flex items-center gap-3.5 shadow-sm group">
                <div class="w-11 h-11 rounded-xl bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center text-cyan-400 text-lg group-hover:scale-105 transition">
                    <i class="fa-solid fa-building-columns"></i>
                </div>
                <div>
                    <div class="text-2xl font-extrabold text-white tracking-tight" id="stat-big-tech">0</div>
                    <div class="text-[11px] font-medium text-slate-400">Big Tech & MNC</div>
                </div>
            </div>
            <div class="bg-[#12141d] border border-[#1e2233] hover:border-[#2b3047] transition rounded-2xl p-4 flex items-center gap-3.5 shadow-sm group">
                <div class="w-11 h-11 rounded-xl bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400 text-lg group-hover:scale-105 transition">
                    <i class="fa-solid fa-rocket"></i>
                </div>
                <div>
                    <div class="text-2xl font-extrabold text-white tracking-tight" id="stat-startups">0</div>
                    <div class="text-[11px] font-medium text-slate-400">Startups & Giants</div>
                </div>
            </div>
            <div class="bg-[#12141d] border border-[#1e2233] hover:border-[#2b3047] transition rounded-2xl p-4 flex items-center gap-3.5 shadow-sm group">
                <div class="w-11 h-11 rounded-xl bg-teal-500/10 border border-teal-500/20 flex items-center justify-center text-teal-400 text-lg group-hover:scale-105 transition">
                    <i class="fa-solid fa-globe"></i>
                </div>
                <div>
                    <div class="text-2xl font-extrabold text-white tracking-tight" id="stat-remote">0</div>
                    <div class="text-[11px] font-medium text-slate-400">Remote Roles</div>
                </div>
            </div>
            <div class="bg-[#12141d] border border-[#1e2233] hover:border-[#2b3047] transition rounded-2xl p-4 flex items-center gap-3.5 shadow-sm group">
                <div class="w-11 h-11 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 text-lg group-hover:scale-105 transition">
                    <i class="fa-solid fa-circle-check"></i>
                </div>
                <div>
                    <div class="text-2xl font-extrabold text-white tracking-tight" id="stat-applied">0</div>
                    <div class="text-[11px] font-medium text-slate-400">Applied Roles</div>
                </div>
            </div>
            <div class="bg-[#12141d] border border-[#1e2233] hover:border-[#2b3047] transition rounded-2xl p-4 flex items-center gap-3.5 shadow-sm group">
                <div class="w-11 h-11 rounded-xl bg-sky-500/10 border border-sky-500/20 flex items-center justify-center text-sky-400 text-lg group-hover:scale-105 transition">
                    <i class="fa-solid fa-layer-group"></i>
                </div>
                <div>
                    <div class="text-2xl font-extrabold text-white tracking-tight" id="stat-total">0</div>
                    <div class="text-[11px] font-medium text-slate-400">Total Shortlisted</div>
                </div>
            </div>
        </div>

        <!-- Section: Upload PDF JD & Instant ATS Resume Generator -->
        <section class="bg-[#12141d] border border-[#1e2233] hover:border-[#282d42] transition rounded-2xl p-5 shadow-lg space-y-4">
            <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-[#1c1f2e] pb-3">
                <div class="flex items-center gap-3">
                    <div class="w-9 h-9 rounded-xl bg-gradient-to-tr from-rose-500/20 via-pink-500/20 to-amber-500/20 text-rose-400 border border-rose-500/30 flex items-center justify-center text-base shadow-sm">
                        <i class="fa-solid fa-file-pdf"></i>
                    </div>
                    <div>
                        <h2 class="text-sm font-bold text-white flex items-center gap-2">
                            Direct PDF Job Description Tailor
                            <span class="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-rose-500/10 text-rose-300 border border-rose-500/20">Auto 1-Page ATS</span>
                        </h2>
                        <p class="text-xs text-slate-400">Upload any role JD in PDF format — AI extracts requirements, computes match score, and compiles a publication-grade ATS resume PDF</p>
                    </div>
                </div>
                <div class="flex items-center gap-2 shrink-0">
                    <span class="text-[11px] text-slate-400 font-medium">Candidate:</span>
                    <span id="pdfUploadActiveCandidate" class="px-2.5 py-1 text-xs font-bold rounded-xl bg-[#181b28] text-sky-400 border border-[#24283b] flex items-center gap-1.5">
                        <i class="fa-solid fa-user-check text-[10px]"></i> Madhav Jayam
                    </span>
                </div>
            </div>

            <!-- Drag & Drop Zone -->
            <div id="pdf-drop-zone"
                 ondragover="handlePdfDragOver(event)"
                 ondragleave="handlePdfDragLeave(event)"
                 ondrop="handlePdfDrop(event)"
                 onclick="document.getElementById('jd-pdf-file-input').click()"
                 class="border-2 border-dashed border-[#24283b] hover:border-sky-500/60 bg-[#0a0c14]/60 hover:bg-[#101424]/60 rounded-xl p-6 text-center cursor-pointer transition flex flex-col items-center justify-center gap-2 group">
                <input type="file" id="jd-pdf-file-input" accept=".pdf,application/pdf" multiple class="hidden" onchange="handlePdfFiles(this.files)" />
                <div class="w-12 h-12 rounded-2xl bg-sky-500/10 text-sky-400 group-hover:scale-110 border border-sky-500/20 flex items-center justify-center text-xl transition shadow-sm">
                    <i class="fa-solid fa-cloud-arrow-up"></i>
                </div>
                <div>
                    <p class="text-xs font-semibold text-slate-200">
                        <span class="text-sky-400 hover:underline">Click to browse</span> or drag & drop Job Description PDF(s) here
                    </p>
                    <p class="text-[11px] text-slate-500 mt-0.5">Supports single or batch upload (.pdf up to 25MB). Auto-parses role requirements & outputs 1-page PDF.</p>
                </div>
            </div>

            <!-- Upload / Processing Queue Container -->
            <div id="pdf-processing-queue" class="hidden space-y-2.5 pt-1"></div>
        </section>

        <!-- Navigation Tabs -->
        <div class="flex items-center gap-5 border-b border-[#1c1f2e] text-xs font-medium overflow-x-auto pb-px">
            <button onclick="switchTab('today')" class="tab-btn pb-3 px-1 text-slate-400 hover:text-slate-200 transition flex items-center gap-1.5" id="tab-btn-today">
                <i class="fa-solid fa-calendar-day text-emerald-400 text-[11px]"></i> Discovered Today <span class="text-[10px] px-1.5 py-0.2 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/30" id="badge-today">0</span>
            </button>
            <button onclick="switchTab('recommended')" class="tab-btn pb-3 px-1 text-slate-400 hover:text-slate-200 transition flex items-center gap-1.5" id="tab-btn-recommended">
                <i class="fa-solid fa-star text-amber-400 text-[11px]"></i> Top Matches <span class="text-[10px] px-1.5 py-0.2 rounded-full bg-[#181b28] text-slate-300 border border-[#24283b]" id="badge-recommended">0</span>
            </button>
            <button onclick="switchTab('fresh')" class="tab-btn active pb-3 px-1 text-slate-400 hover:text-slate-200 transition flex items-center gap-1.5" id="tab-btn-fresh">
                <i class="fa-solid fa-bolt text-amber-400 text-[11px]"></i> Fresh Drops (48h) <span class="text-[10px] px-1.5 py-0.2 rounded-full bg-[#181b28] text-slate-300 border border-[#24283b]" id="badge-fresh">0</span>
            </button>
            <button onclick="switchTab('remote')" class="tab-btn pb-3 px-1 text-slate-400 hover:text-slate-200 transition flex items-center gap-1.5" id="tab-btn-remote">
                <i class="fa-solid fa-globe text-cyan-400 text-[11px]"></i> Remote <span class="text-[10px] px-1.5 py-0.2 rounded-full bg-[#181b28] text-slate-300 border border-[#24283b]" id="badge-remote">0</span>
            </button>
            <button onclick="switchTab('big_tech')" class="tab-btn pb-3 px-1 text-slate-400 hover:text-slate-200 transition flex items-center gap-1.5" id="tab-btn-big_tech">
                <i class="fa-solid fa-building-columns text-cyan-400 text-[11px]"></i> Big Tech & MNCs <span class="text-[10px] px-1.5 py-0.2 rounded-full bg-[#181b28] text-slate-300 border border-[#24283b]" id="badge-big_tech">0</span>
            </button>
            <button onclick="switchTab('unicorns')" class="tab-btn pb-3 px-1 text-slate-400 hover:text-slate-200 transition flex items-center gap-1.5" id="tab-btn-unicorns">
                <i class="fa-solid fa-wand-magic-sparkles text-amber-400 text-[11px]"></i> Unicorns & Giants <span class="text-[10px] px-1.5 py-0.2 rounded-full bg-[#181b28] text-slate-300 border border-[#24283b]" id="badge-unicorns">0</span>
            </button>
            <button onclick="switchTab('startups')" class="tab-btn pb-3 px-1 text-slate-400 hover:text-slate-200 transition flex items-center gap-1.5" id="tab-btn-startups">
                <i class="fa-solid fa-rocket text-indigo-400 text-[11px]"></i> AI & Tech Startups <span class="text-[10px] px-1.5 py-0.2 rounded-full bg-[#181b28] text-slate-300 border border-[#24283b]" id="badge-startups">0</span>
            </button>
            <button onclick="switchTab('it_services')" class="tab-btn pb-3 px-1 text-slate-400 hover:text-slate-200 transition flex items-center gap-1.5" id="tab-btn-it_services">
                <i class="fa-solid fa-building text-slate-400 text-[11px]"></i> IT Services <span class="text-[10px] px-1.5 py-0.2 rounded-full bg-[#181b28] text-slate-300 border border-[#24283b]" id="badge-it_services">0</span>
            </button>
            <button onclick="switchTab('all')" class="tab-btn pb-3 px-1 text-slate-400 hover:text-slate-200 transition flex items-center gap-1.5" id="tab-btn-all">
                <i class="fa-solid fa-list-check text-[11px]"></i> All Shortlisted <span class="text-[10px] px-1.5 py-0.2 rounded-full bg-[#181b28] text-slate-300 border border-[#24283b]" id="badge-all">0</span>
            </button>
            <button onclick="switchTab('applied')" class="tab-btn pb-3 px-1 text-slate-400 hover:text-slate-200 transition flex items-center gap-1.5" id="tab-btn-applied">
                <i class="fa-solid fa-circle-check text-emerald-400 text-[11px]"></i> Applied Tracker <span class="text-[10px] px-1.5 py-0.2 rounded-full bg-[#181b28] text-slate-300 border border-[#24283b]" id="badge-applied">0</span>
            </button>
        </div>

        <!-- Search, Filter & Sort Controls -->
        <div class="bg-[#12141d] border border-[#1e2233] rounded-2xl p-3 flex flex-col sm:flex-row items-center justify-between gap-3 shadow-sm">
            <div class="relative flex-1 w-full">
                <i class="fa-solid fa-magnifying-glass absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-500 text-xs"></i>
                <input type="text" id="search-input" oninput="handleSearch()" placeholder="Search title, company, skills (e.g. PyTorch, React, Python), location..." class="w-full pl-9 pr-8 py-2 text-xs bg-[#0a0c14] border border-[#1e2233] rounded-xl text-slate-100 placeholder-slate-500 focus:outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500 transition">
                <button id="search-clear-btn" onclick="clearSearch()" class="hidden absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 text-xs p-1" title="Clear search">
                    <i class="fa-solid fa-xmark"></i>
                </button>
            </div>
            <div class="flex items-center justify-between sm:justify-end w-full sm:w-auto gap-2.5 shrink-0">
                <div class="flex items-center gap-2">
                    <label for="sort-select" class="text-xs text-slate-400 font-medium whitespace-nowrap"><i class="fa-solid fa-arrow-down-short-wide text-slate-500"></i> Sort:</label>
                    <select id="sort-select" onchange="handleSort()" class="px-2.5 py-2 text-xs bg-[#0a0c14] border border-[#1e2233] rounded-xl text-slate-300 focus:outline-none focus:border-sky-500 cursor-pointer">
                        <option value="match_desc">Match % (High → Low)</option>
                        <option value="date_desc">Newest First</option>
                        <option value="company_asc">Company (A → Z)</option>
                        <option value="title_asc">Role Title (A → Z)</option>
                    </select>
                </div>
                <div class="text-xs font-semibold px-2.5 py-1.5 rounded-xl bg-[#181b28] text-slate-300 border border-[#24283b] whitespace-nowrap" id="search-counter">
                    0 roles
                </div>
            </div>
        </div>

        <!-- Job Cards Grid -->
        <div id="jobs-container" class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <!-- Rendered dynamically -->
        </div>
    </main>

    <!-- Job Details & Match Modal (Native HTML5 Dialog) -->
    <dialog id="job-details-modal" class="bg-[#12141d] text-slate-100 border border-[#24283b] rounded-2xl p-0 w-full max-w-3xl shadow-2xl shadow-black/80 m-auto overflow-hidden">
        <div class="flex flex-col max-h-[90vh]">
            <!-- Header -->
            <div class="px-6 py-4 border-b border-[#1c1f2e] flex items-start justify-between gap-4 bg-[#12141d]/95 sticky top-0 z-10">
                <div class="space-y-1.5">
                    <div class="flex items-center gap-2 flex-wrap" id="modal-badges"></div>
                    <h2 class="text-xl font-bold text-white leading-tight" id="modal-title">Job Title</h2>
                    <p class="text-sm text-slate-400 font-medium" id="modal-subtitle">Company • Location</p>
                </div>
                <button onclick="closeDetailsModal()" class="w-8 h-8 rounded-lg bg-[#181b28] hover:bg-[#222638] text-slate-400 hover:text-white flex items-center justify-center transition shrink-0" aria-label="Close dialog">
                    <i class="fa-solid fa-xmark"></i>
                </button>
            </div>
            
            <!-- Scrollable Content -->
            <div class="p-6 space-y-5 overflow-y-auto">
                <!-- AI Match Analysis Box -->
                <div id="modal-match-section" class="bg-[#0a0c14] border border-[#1e2233] rounded-xl p-4 space-y-2">
                    <div class="flex items-center justify-between">
                        <span class="text-xs font-bold uppercase tracking-wider text-sky-400 flex items-center gap-1.5">
                            <i class="fa-solid fa-wand-magic-sparkles"></i> AI Match Analysis
                        </span>
                        <span id="modal-score-badge" class="px-2.5 py-0.5 rounded text-xs font-extrabold border"></span>
                    </div>
                    <div id="modal-matching-notes" class="text-xs text-slate-300 leading-relaxed"></div>
                </div>

                <!-- Skills Chips -->
                <div id="modal-skills-section" class="space-y-2">
                    <h3 class="text-xs font-bold uppercase tracking-wider text-slate-400">Extracted Skills & Requirements</h3>
                    <div id="modal-skills-chips" class="flex flex-wrap gap-1.5"></div>
                </div>

                <!-- Full Job Description -->
                <div class="space-y-2">
                    <h3 class="text-xs font-bold uppercase tracking-wider text-slate-400">Full Job Description</h3>
                    <div id="modal-description" class="text-xs text-slate-300 whitespace-pre-wrap font-sans bg-[#0a0c14] p-4 rounded-xl border border-[#1e2233] leading-relaxed max-h-80 overflow-y-auto select-text"></div>
                </div>
            </div>

            <!-- Footer Actions -->
            <div class="px-6 py-4 border-t border-[#1c1f2e] bg-[#12141d]/95 flex items-center justify-between gap-3 sticky bottom-0">
                <button id="modal-dismiss-btn" class="px-4 py-2 text-xs font-medium text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 rounded-xl transition border border-transparent hover:border-rose-500/20">
                    <i class="fa-solid fa-xmark mr-1"></i> Dismiss
                </button>
                <div class="flex items-center gap-2">
                    <a id="modal-listing-link" href="#" target="_blank" rel="noopener noreferrer" class="px-4 py-2 text-xs font-medium bg-[#181b28] hover:bg-[#222638] text-slate-200 rounded-xl border border-[#24283b] flex items-center gap-1.5 transition">
                        <i class="fa-solid fa-arrow-up-right-from-square text-sky-400"></i> View Listing
                    </a>
                    <a id="modal-pdf-link" href="#" target="_blank" class="hidden px-4 py-2 text-xs font-medium bg-[#181b28] hover:bg-[#222638] text-sky-400 rounded-xl border border-[#24283b] flex items-center gap-1.5 transition">
                        <i class="fa-solid fa-file-pdf"></i> View PDF
                    </a>
                    <button id="modal-reveal-btn" onclick="revealInFinder(currentModalPdfPath)" class="hidden px-3 py-2 text-xs font-medium bg-[#181b28] hover:bg-[#222638] text-slate-300 rounded-xl border border-[#24283b] flex items-center gap-1.5 transition" title="Reveal PDF in Finder & copy path">
                        <i class="fa-regular fa-folder-open text-amber-400"></i> Finder
                    </button>
                    <button id="modal-mark-applied-btn" class="px-4 py-2 text-xs font-semibold text-emerald-400 hover:text-white bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/30 rounded-xl transition flex items-center gap-1.5" title="Mark as applied and sync to Notion">
                        <i class="fa-solid fa-check"></i> Mark Applied
                    </button>
                    <button id="modal-apply-btn" class="px-5 py-2 text-xs font-bold bg-gradient-to-r from-sky-500 via-indigo-500 to-teal-500 hover:from-sky-400 hover:to-teal-400 text-white rounded-xl shadow-md shadow-sky-500/20 flex items-center gap-1.5 transition">
                        <i class="fa-solid fa-bolt text-yellow-300"></i> 1-Click Tailor & Apply
                    </button>
                </div>
            </div>
        </div>
    </dialog>

    <!-- Apply Outcome Confirmation Modal -->
    <dialog id="apply-outcome-modal" class="bg-[#12141d] text-slate-100 border border-[#24283b] rounded-2xl p-6 w-full max-w-md shadow-2xl shadow-black/80 m-auto backdrop:bg-black/70">
        <div class="text-center space-y-4">
            <div class="w-14 h-14 bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded-full flex items-center justify-center mx-auto text-2xl">
                <i class="fa-solid fa-paper-plane"></i>
            </div>
            <div>
                <h3 class="text-lg font-bold text-white" id="outcome-modal-title">Application Submitted?</h3>
                <p id="outcome-modal-subtitle" class="text-xs text-slate-400 mt-1">Target listing opened & resume ready. Did you submit the application?</p>
            </div>
            <div class="flex flex-col gap-2 pt-2">
                <button id="outcome-applied-btn" class="w-full py-2.5 px-4 bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-400 hover:to-teal-500 text-white font-bold text-xs rounded-xl shadow-lg shadow-emerald-500/20 transition flex items-center justify-center gap-2">
                    <i class="fa-solid fa-check"></i> Yes, Mark as Applied (Sync to Notion)
                </button>
                <button id="outcome-skip-btn" class="w-full py-2 px-4 bg-[#181b28] hover:bg-[#222638] text-slate-300 font-medium text-xs rounded-xl border border-[#24283b] transition">
                    Keep in Shortlist (Decide Later)
                </button>
                <button id="outcome-expired-btn" class="w-full py-1.5 px-4 text-slate-500 hover:text-rose-400 text-xs transition">
                    Job is Expired / Closed
                </button>
            </div>
        </div>
    </dialog>

    <!-- Add Custom Job Modal (Native HTML5 Dialog) -->
    <dialog id="custom-job-modal" class="bg-[#12141d] text-slate-100 border border-[#24283b] rounded-2xl p-0 w-full max-w-lg shadow-2xl shadow-black/80 m-auto overflow-hidden">
        <form method="dialog" onsubmit="submitCustomJob(event)" class="p-6 space-y-4">
            <div class="flex items-center justify-between border-b border-[#1c1f2e] pb-3">
                <div class="flex items-center gap-2.5">
                    <div class="w-8 h-8 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center justify-center">
                        <i class="fa-solid fa-plus"></i>
                    </div>
                    <div>
                        <h2 class="text-base font-bold text-white">Add Custom Job Listing</h2>
                        <p class="text-xs text-slate-400">Extract, screen with AI, and tailor resume</p>
                    </div>
                </div>
                <button type="button" onclick="closeCustomJobModal()" class="text-slate-400 hover:text-white transition">
                    <i class="fa-solid fa-xmark"></i>
                </button>
            </div>

            <div class="space-y-3">
                <div>
                    <label class="block text-xs font-semibold text-slate-300 mb-1">Job Listing URL</label>
                    <div class="flex gap-2">
                        <input type="url" id="custom-url-input" placeholder="https://jobs.lever.co/..., greenhouse.io, linkedin..." class="flex-1 px-3 py-2 text-xs bg-[#0a0c14] border border-[#1e2233] rounded-xl focus:outline-none focus:border-sky-500 text-slate-100" />
                        <button type="button" onclick="pasteCustomUrl()" class="px-3 py-2 text-xs bg-[#181b28] hover:bg-[#222638] text-slate-300 rounded-xl border border-[#24283b] transition" title="Paste from clipboard">
                            <i class="fa-solid fa-paste"></i>
                        </button>
                    </div>
                </div>

                <div>
                    <label class="block text-xs font-semibold text-slate-300 mb-1">OR Upload JD PDF</label>
                    <input type="file" id="custom-pdf-input" accept=".pdf,application/pdf" class="w-full text-xs text-slate-400 file:mr-2 file:py-1.5 file:px-3 file:rounded-xl file:border-0 file:text-xs file:font-semibold file:bg-[#181b28] file:text-sky-400 hover:file:bg-[#222638] cursor-pointer" />
                </div>

                <div>
                    <label class="block text-xs font-semibold text-slate-300 mb-1">Raw Job Description (Optional fallback)</label>
                    <textarea id="custom-text-input" rows="3" placeholder="If the role is behind a login or private portal, paste the JD text here..." class="w-full px-3 py-2 text-xs bg-[#0a0c14] border border-[#1e2233] rounded-xl focus:outline-none focus:border-sky-500 text-slate-100 resize-none font-mono text-[11px]"></textarea>
                </div>
            </div>

            <div id="custom-job-progress" class="hidden p-3 rounded-xl bg-sky-500/10 border border-sky-500/20 text-xs text-sky-300 flex items-center gap-2">
                <i class="fa-solid fa-circle-notch fa-spin text-sky-400"></i>
                <span id="custom-job-status-text">Ingesting listing and screening with AI...</span>
            </div>

            <div class="flex items-center justify-end gap-2 pt-2 border-t border-[#1c1f2e]">
                <button type="button" onclick="closeCustomJobModal()" class="px-4 py-2 text-xs font-medium bg-[#181b28] hover:bg-[#222638] text-slate-300 rounded-xl border border-[#24283b] transition">
                    Cancel
                </button>
                <button type="submit" id="custom-submit-btn" class="px-4 py-2 text-xs font-bold bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-400 hover:to-teal-500 text-white rounded-xl shadow-sm flex items-center gap-1.5 transition">
                    <i class="fa-solid fa-wand-magic-sparkles"></i> Analyze & Ingest
                </button>
            </div>
        </form>
    </dialog>

    <!-- Notification Toast with Undo -->
    <div id="toast" class="fixed bottom-6 right-6 px-4 py-3 rounded-2xl bg-[#12141d] border border-[#24283b] text-sm shadow-2xl transition-all duration-300 transform translate-y-24 opacity-0 z-50 flex items-center gap-3 max-w-md">
        <i id="toast-icon" class="fa-solid fa-circle-check text-emerald-400 text-lg shrink-0"></i>
        <div id="toast-msg" class="text-slate-200 font-medium text-xs flex-1">Notification message</div>
        <button id="toast-undo-btn" class="hidden px-2.5 py-1 text-xs font-bold bg-sky-500/20 text-sky-400 hover:bg-sky-500/30 rounded border border-sky-500/30 transition shrink-0">
            Undo
        </button>
    </div>

    <script>
        let currentTab = 'fresh';
        let rawData = null;
        let searchTerm = '';
        let currentSort = 'match_desc';
        let toastTimer = null;
        let currentModalPdfPath = '';
        let currentProfile = localStorage.getItem('active_profile') || 'madhav';

        function updateCandidateBadges() {
            const candEl = document.getElementById('pdfUploadActiveCandidate');
            if (candEl) {
                candEl.innerHTML = `<i class="fa-solid fa-user-check text-[10px]"></i> ${currentProfile === 'mahika' ? 'Mahika Neranjen' : 'Madhav Jayam'}`;
            }
        }

        function onProfileChange(val) {
            currentProfile = val;
            localStorage.setItem('active_profile', val);
            showToast(`Active Profile: ${val === 'mahika' ? 'Mahika Neranjen' : 'Madhav Jayam'}`);
            updateCandidateBadges();
        }

        async function revealInFinder(pdfPath) {
            if (!pdfPath) return;
            try {
                await navigator.clipboard.writeText(pdfPath);
            } catch (_) {}
            try {
                const res = await fetch('/api/reveal', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path: pdfPath })
                });
                const data = await res.json();
                if (data.success) {
                    showToast('Revealed in Finder & path copied to clipboard!');
                } else {
                    showToast('Path copied to clipboard: ' + pdfPath);
                }
            } catch (_) {
                showToast('Path copied: ' + pdfPath);
            }
        }

        function escapeHtml(str) {
            if (!str) return '';
            return String(str)
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");
        }

        function showToast(msg, isError = false, undoCallback = null) {
            const toast = document.getElementById('toast');
            const icon = document.getElementById('toast-icon');
            const msgEl = document.getElementById('toast-msg');
            const undoBtn = document.getElementById('toast-undo-btn');

            if (toastTimer) clearTimeout(toastTimer);

            msgEl.innerText = msg;
            icon.className = isError
                ? 'fa-solid fa-triangle-exclamation text-rose-400 text-lg shrink-0'
                : 'fa-solid fa-circle-check text-emerald-400 text-lg shrink-0';

            if (undoCallback) {
                undoBtn.classList.remove('hidden');
                undoBtn.onclick = () => {
                    undoBtn.classList.add('hidden');
                    toast.classList.add('translate-y-24', 'opacity-0');
                    undoCallback();
                };
            } else {
                undoBtn.classList.add('hidden');
            }

            toast.classList.remove('translate-y-24', 'opacity-0');
            toastTimer = setTimeout(() => {
                toast.classList.add('translate-y-24', 'opacity-0');
            }, undoCallback ? 7000 : 4000);
        }

        async function fetchJobs() {
            try {
                const res = await fetch('/api/jobs');
                rawData = await res.json();
                renderMetrics();
                renderCards();
            } catch (e) {
                showToast('Failed to load jobs: ' + e, true);
            }
        }

        function renderMetrics() {
            if (!rawData || !rawData.stats) return;
            const s = rawData.stats;
            if (document.getElementById('stat-discovered-today')) document.getElementById('stat-discovered-today').innerText = s.discovered_today || 0;
            if (document.getElementById('stat-fresh')) document.getElementById('stat-fresh').innerText = s.fresh_48h || 0;
            if (document.getElementById('stat-big-tech')) document.getElementById('stat-big-tech').innerText = s.big_tech_count || 0;
            if (document.getElementById('stat-startups')) document.getElementById('stat-startups').innerText = (s.startup_count || 0) + (s.unicorn_count || 0);
            if (document.getElementById('stat-remote')) document.getElementById('stat-remote').innerText = s.remote_count || 0;
            if (document.getElementById('stat-applied')) document.getElementById('stat-applied').innerText = s.total_applied || 0;
            if (document.getElementById('stat-total')) document.getElementById('stat-total').innerText = s.total_shortlisted || 0;

            if (document.getElementById('badge-today')) document.getElementById('badge-today').innerText = s.discovered_today || 0;
            if (document.getElementById('badge-fresh')) document.getElementById('badge-fresh').innerText = s.fresh_48h || 0;
            if (document.getElementById('badge-recommended')) document.getElementById('badge-recommended').innerText = s.recommended_count || 0;
            if (document.getElementById('badge-remote')) document.getElementById('badge-remote').innerText = s.remote_count || 0;
            if (document.getElementById('badge-big_tech')) document.getElementById('badge-big_tech').innerText = s.big_tech_count || 0;
            if (document.getElementById('badge-unicorns')) document.getElementById('badge-unicorns').innerText = s.unicorn_count || 0;
            if (document.getElementById('badge-startups')) document.getElementById('badge-startups').innerText = s.startup_count || 0;
            if (document.getElementById('badge-it_services')) document.getElementById('badge-it_services').innerText = s.it_services_count || 0;
            if (document.getElementById('badge-all')) document.getElementById('badge-all').innerText = s.total_shortlisted || 0;
            if (document.getElementById('badge-applied')) document.getElementById('badge-applied').innerText = s.total_applied || 0;
        }

        function switchTab(tab) {
            currentTab = tab;
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            const activeBtn = document.getElementById('tab-btn-' + tab);
            if (activeBtn) activeBtn.classList.add('active');
            renderCards();
        }

        function handleSearch() {
            const input = document.getElementById('search-input');
            searchTerm = (input.value || '').trim().toLowerCase();
            const clearBtn = document.getElementById('search-clear-btn');
            if (searchTerm) {
                clearBtn.classList.remove('hidden');
            } else {
                clearBtn.classList.add('hidden');
            }
            renderCards();
        }

        function clearSearch() {
            const input = document.getElementById('search-input');
            input.value = '';
            searchTerm = '';
            document.getElementById('search-clear-btn').classList.add('hidden');
            renderCards();
        }

        function handleSort() {
            currentSort = document.getElementById('sort-select').value;
            renderCards();
        }

        function getFilteredAndSortedJobs(list) {
            if (!list) return [];
            let res = list.slice();

            // 1. Text Search Filter across key attributes
            if (searchTerm) {
                const tokens = searchTerm.split(/\s+/).filter(Boolean);
                res = res.filter(j => {
                    const searchable = [
                        j.title,
                        j.company,
                        j.location,
                        j.skills,
                        j.platform,
                        j.matching_notes
                    ].filter(Boolean).join(' ').toLowerCase();
                    return tokens.every(t => searchable.includes(t));
                });
            }

            // 2. Sort
            res.sort((a, b) => {
                if (currentSort === 'match_desc') {
                    return (b.score || 0) - (a.score || 0);
                } else if (currentSort === 'date_desc') {
                    return (b.created_at || '').localeCompare(a.created_at || '');
                } else if (currentSort === 'company_asc') {
                    return (a.company || '').localeCompare(b.company || '');
                } else if (currentSort === 'title_asc') {
                    return (a.title || '').localeCompare(b.title || '');
                }
                return 0;
            });

            return res;
        }

        function updateResultCounter(shown, total) {
            const counter = document.getElementById('search-counter');
            if (!counter) return;
            if (searchTerm) {
                counter.innerText = `Showing ${shown} of ${total} roles`;
            } else {
                counter.innerText = `${shown} roles`;
            }
        }

        function renderCards() {
            const container = document.getElementById('jobs-container');
            container.innerHTML = '';

            if (!rawData) return;

            let list = [];
            if (currentTab === 'today') list = rawData.today_jobs;
            else if (currentTab === 'recommended') list = rawData.recommended_jobs;
            else if (currentTab === 'fresh') list = rawData.fresh_jobs;
            else if (currentTab === 'remote') list = rawData.remote_jobs;
            else if (currentTab === 'big_tech') list = rawData.big_tech_jobs;
            else if (currentTab === 'unicorns') list = rawData.unicorn_jobs;
            else if (currentTab === 'startups') list = rawData.startup_jobs;
            else if (currentTab === 'it_services') list = rawData.it_services_jobs;
            else if (currentTab === 'tier1') list = rawData.tier1_jobs;
            else if (currentTab === 'tier2') list = rawData.tier2_jobs;
            else if (currentTab === 'all') list = rawData.all_shortlisted;
            else if (currentTab === 'applied') list = rawData.applied_jobs;

            const filtered = getFilteredAndSortedJobs(list);
            updateResultCounter(filtered.length, (list || []).length);

            if (!filtered || filtered.length === 0) {
                const emptyMsg = (currentTab === 'today')
                    ? 'No new roles discovered yet today. Discovery runs automatically on schedule.'
                    : 'No postings match your current filter.';
                container.innerHTML = `
                    <div class="col-span-1 md:col-span-2 py-16 text-center text-slate-500">
                        <i class="fa-regular fa-folder-open text-4xl mb-3 block text-slate-600"></i>
                        <p class="text-sm font-medium text-slate-400">${emptyMsg}</p>
                        ${searchTerm ? `<button onclick="clearSearch()" class="mt-2 text-xs text-sky-400 hover:underline">Clear search filter</button>` : ''}
                    </div>
                `;
                return;
            }

            if (currentTab === 'today' && (!searchTerm || searchTerm.length === 0)) {
                const todayBanner = document.createElement('div');
                todayBanner.className = "col-span-1 md:col-span-2 bg-gradient-to-r from-emerald-950/40 via-[#12141d] to-[#12141d] border border-emerald-500/30 rounded-2xl p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-md";
                const totalScrapedToday = (rawData.stats && rawData.stats.total_discovered_today) ? rawData.stats.total_discovered_today : ((list || []).length);
                const todayDateFormatted = new Date().toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'short', day: 'numeric' });
                todayBanner.innerHTML = `
                    <div class="flex items-center gap-3">
                        <div class="w-10 h-10 rounded-xl bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center text-emerald-400 text-lg shrink-0">
                            <i class="fa-solid fa-calendar-day"></i>
                        </div>
                        <div>
                            <h3 class="text-sm font-bold text-white flex items-center gap-2">
                                Newly Discovered Today
                                <span class="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-mono">${(list || []).length} Shortlisted Roles</span>
                            </h3>
                            <p class="text-xs text-slate-400 mt-0.5">Discovered ${todayDateFormatted} &bull; ${totalScrapedToday} total listings screened across ATS pipelines.</p>
                        </div>
                    </div>
                    <div class="flex items-center gap-2 shrink-0 text-xs text-slate-400">
                        <span class="px-2.5 py-1 rounded-xl bg-[#0a0c14] border border-[#1e2233] text-emerald-400 font-medium flex items-center gap-1.5">
                            <i class="fa-solid fa-circle-check text-[10px]"></i> Live ATS Discovery Active
                        </span>
                    </div>
                `;
                container.appendChild(todayBanner);
            }

            const todayStr = new Date().toISOString().slice(0, 10);
            filtered.forEach(j => {
                const scoreColor = (j.score >= 90) ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20'
                                 : (j.score >= 80) ? 'text-sky-400 bg-sky-500/10 border-sky-500/20'
                                 : 'text-amber-400 bg-amber-500/10 border-amber-500/20';
                
                const isToday = (j.created_at || '').startsWith(todayStr);
                const todayBadge = isToday ? `<span class="text-[10px] px-2 py-0.5 rounded-md bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-semibold flex items-center gap-1"><i class="fa-solid fa-sparkles text-[9px]"></i> Today</span>` : '';

                let tierBadge = '';
                const cat = (j.tier || '').toLowerCase();
                if (cat.includes('big tech') || cat.includes('mnc')) {
                    tierBadge = `<span class="text-[10px] px-2 py-0.5 rounded-md bg-cyan-500/10 text-cyan-300 border border-cyan-500/20 font-semibold flex items-center gap-1"><i class="fa-solid fa-building-columns text-[9px]"></i> Big Tech & MNC</span>`;
                } else if (cat.includes('unicorn') || cat.includes('giant')) {
                    tierBadge = `<span class="text-[10px] px-2 py-0.5 rounded-md bg-amber-500/10 text-amber-300 border border-amber-500/20 font-semibold flex items-center gap-1"><i class="fa-solid fa-wand-magic-sparkles text-[9px]"></i> Unicorn</span>`;
                } else if (cat.includes('startup')) {
                    tierBadge = `<span class="text-[10px] px-2 py-0.5 rounded-md bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 font-semibold flex items-center gap-1"><i class="fa-solid fa-rocket text-[9px]"></i> Startup</span>`;
                } else if (cat.includes('it services') || cat.includes('service') || cat.includes('consult')) {
                    tierBadge = `<span class="text-[10px] px-2 py-0.5 rounded-md bg-slate-500/15 text-slate-300 border border-slate-500/30 font-semibold flex items-center gap-1"><i class="fa-solid fa-building text-[9px]"></i> IT Services</span>`;
                } else if (j.tier) {
                    tierBadge = `<span class="text-[10px] px-2 py-0.5 rounded-md bg-[#181b28] text-slate-300 border border-[#24283b] font-medium">${escapeHtml(j.tier.split(':')[0])}</span>`;
                }
                const isRemote = j.is_remote_verified;
                const remoteBadge = isRemote ? `<span class="text-[10px] px-2 py-0.5 rounded-md bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 font-medium flex items-center gap-1"><i class="fa-solid fa-globe text-[9px]"></i> Remote</span>` : '';
                const platformBadge = j.platform ? `<span class="text-[10px] px-2 py-0.5 rounded-md bg-sky-500/10 text-sky-400 border border-sky-500/20 font-mono">${j.platform}</span>` : '';
                const datePosted = j.date_posted && j.date_posted !== 'nan' ? j.date_posted : 'Recent';
                const hasPdf = j.tailored_resume_pdf_path ? true : false;
                const listingUrl = (j.job_url_direct || j.job_url || '').trim();
                const portalUrl = (j.status_portal_url || '').trim();

                const card = document.createElement('div');
                card.className = "bg-[#12141d] border border-[#1e2233] hover:border-[#2f354f] rounded-2xl p-5 hover:shadow-xl hover:shadow-sky-500/5 transition duration-200 flex flex-col justify-between space-y-4 shadow-sm";
                card.id = `job-${j.job_id}`;

                if (currentTab === 'applied') {
                    card.innerHTML = `
                        <div class="space-y-2">
                            <div class="flex items-start justify-between gap-3">
                                <div>
                                    <div class="flex items-center gap-2 mb-1">
                                        ${platformBadge}
                                        <span class="text-[10px] text-slate-500"><i class="fa-regular fa-clock"></i> Applied ${j.created_at || 'Recently'}</span>
                                    </div>
                                    <h3 class="text-base font-bold text-white leading-snug">
                                        ${listingUrl ? `<a href="${listingUrl}" target="_blank" rel="noopener noreferrer" class="hover:text-sky-400 transition inline-flex items-center gap-1.5">${escapeHtml(j.title)} <i class="fa-solid fa-arrow-up-right-from-square text-[11px] text-slate-500"></i></a>` : escapeHtml(j.title)}
                                    </h3>
                                    <p class="text-sm font-medium text-slate-300 mt-0.5">${escapeHtml(j.company)} &bull; <span class="text-xs text-slate-400">${escapeHtml(j.location || 'Remote/India')}</span></p>
                                </div>
                                <span class="px-2.5 py-1 text-xs font-bold rounded-lg border text-emerald-400 bg-emerald-500/10 border-emerald-500/20 shrink-0">Applied</span>
                            </div>
                        </div>
                        <div class="flex items-center justify-between pt-3 border-t border-[#1c1f2e] gap-2 flex-wrap">
                            <button onclick="openDetailsModal('${j.job_id}')" class="px-3.5 py-1.5 text-xs font-medium text-slate-300 hover:text-white bg-[#181b28] hover:bg-[#222638] rounded-xl border border-[#24283b] flex items-center gap-1.5 transition shadow-sm" title="View Job Description & Tailoring Notes">
                                <i class="fa-solid fa-eye text-[10px] text-indigo-400"></i> Details
                            </button>
                            <div class="flex items-center gap-2">
                                ${portalUrl ? `<a href="${portalUrl}" target="_blank" rel="noopener noreferrer" class="px-3.5 py-1.5 text-xs font-bold bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white rounded-xl shadow-sm flex items-center gap-1.5 transition" title="Open candidate application status tracking portal"><i class="fa-solid fa-id-card"></i> Check Status (${j.platform || 'Portal'})</a>` : ''}
                                ${listingUrl ? `<a href="${listingUrl}" target="_blank" rel="noopener noreferrer" class="px-3.5 py-1.5 text-xs font-medium bg-[#181b28] hover:bg-[#222638] text-slate-300 hover:text-white rounded-xl border border-[#24283b] flex items-center gap-1.5 transition"><i class="fa-solid fa-arrow-up-right-from-square text-[10px] text-sky-400"></i> View Listing</a>` : ''}
                                ${hasPdf ? `
                                <button onclick="revealInFinder('${escapeHtml(j.tailored_resume_pdf_path)}')" class="px-2.5 py-1.5 text-xs font-medium bg-[#181b28] hover:bg-[#222638] text-slate-300 hover:text-white rounded-xl border border-[#24283b] flex items-center gap-1 transition" title="Reveal PDF in Finder & copy path"><i class="fa-regular fa-folder-open text-amber-400"></i></button>
                                <a href="/pdf?path=${encodeURIComponent(j.tailored_resume_pdf_path)}" target="_blank" class="px-3 py-1.5 text-xs font-medium bg-[#181b28] hover:bg-[#222638] text-sky-400 rounded-xl border border-[#24283b] flex items-center gap-1.5 transition"><i class="fa-solid fa-file-pdf"></i> View PDF</a>` : ''}
                            </div>
                        </div>
                    `;
                } else {
                    card.innerHTML = `
                        <div class="space-y-3">
                            <div class="flex items-start justify-between gap-2">
                                <div class="space-y-1">
                                    <div class="flex items-center gap-2 flex-wrap">
                                        ${todayBadge}
                                        ${tierBadge}
                                        ${remoteBadge}
                                        <span class="text-[10px] text-slate-400"><i class="fa-regular fa-clock"></i> ${datePosted}</span>
                                    </div>
                                    <h3 class="text-base font-bold text-white leading-snug">
                                        ${listingUrl ? `<a href="${listingUrl}" target="_blank" rel="noopener noreferrer" class="hover:text-sky-400 transition inline-flex items-center gap-1.5">${escapeHtml(j.title)} <i class="fa-solid fa-arrow-up-right-from-square text-[11px] text-slate-500"></i></a>` : escapeHtml(j.title)}
                                    </h3>
                                    <p class="text-sm font-medium text-slate-300">${escapeHtml(j.company)} <span class="text-xs text-slate-400">&bull; ${escapeHtml(j.location || 'India')}</span></p>
                                </div>
                                <div class="px-2.5 py-1 text-xs font-extrabold rounded-lg border ${scoreColor} shrink-0">
                                    ${j.score}% Match
                                </div>
                            </div>
                            ${j.matching_notes ? `<p class="text-xs text-slate-300 bg-[#0a0c14] p-3 rounded-xl border border-[#1e2233] leading-relaxed"><i class="fa-solid fa-circle-info text-sky-400 mr-1"></i> ${escapeHtml(j.matching_notes)}</p>` : ''}
                        </div>

                        <div class="flex items-center justify-between pt-3 border-t border-[#1c1f2e] gap-2 flex-wrap">
                            <div class="flex items-center gap-2">
                                <button onclick="dismissJob('${j.job_id}')" class="px-3 py-1.5 text-xs font-medium text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 rounded-xl transition border border-transparent hover:border-rose-500/20" title="Dismiss from shortlist">
                                    <i class="fa-solid fa-xmark"></i> Dismiss
                                </button>
                                <button onclick="openDetailsModal('${j.job_id}')" class="px-3.5 py-1.5 text-xs font-medium text-slate-300 hover:text-white bg-[#181b28] hover:bg-[#222638] rounded-xl border border-[#24283b] flex items-center gap-1.5 transition shadow-sm" title="View Full Description & Match Details">
                                    <i class="fa-solid fa-eye text-[10px] text-indigo-400"></i> Details
                                </button>
                                ${listingUrl ? `
                                <a href="${listingUrl}" target="_blank" rel="noopener noreferrer" class="px-3.5 py-1.5 text-xs font-medium text-slate-300 hover:text-white bg-[#181b28] hover:bg-[#222638] rounded-xl border border-[#24283b] flex items-center gap-1.5 transition shadow-sm" title="View original job listing in a new tab">
                                    <i class="fa-solid fa-arrow-up-right-from-square text-[10px] text-sky-400"></i> View Listing
                                </a>` : ''}
                            </div>
                            <div class="flex items-center gap-2">
                                ${hasPdf ? `
                                <button onclick="revealInFinder('${escapeHtml(j.tailored_resume_pdf_path)}')" class="px-2.5 py-1.5 text-xs font-medium bg-[#181b28] hover:bg-[#222638] text-slate-300 hover:text-white rounded-xl border border-[#24283b] flex items-center gap-1 transition" title="Reveal PDF in Finder & copy path"><i class="fa-regular fa-folder-open text-amber-400"></i></button>
                                <a href="/pdf?path=${encodeURIComponent(j.tailored_resume_pdf_path)}" target="_blank" class="px-3 py-1.5 text-xs font-medium bg-[#181b28] hover:bg-[#222638] text-sky-400 rounded-xl border border-[#24283b] flex items-center gap-1.5 transition" title="Open Tailored Resume PDF"><i class="fa-solid fa-file-pdf"></i> PDF</a>` : ''}
                                <button onclick="markAppliedDirect('${j.job_id}', this)" class="px-3 py-1.5 text-xs font-semibold text-emerald-400 hover:text-white bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/30 rounded-xl transition flex items-center gap-1.5 shadow-sm" title="Mark as applied & sync to Notion">
                                    <i class="fa-solid fa-check"></i> Applied
                                </button>
                                <button onclick="applyJob('${j.job_id}', this)" class="px-4 py-1.5 text-xs font-bold bg-gradient-to-r from-sky-500 via-indigo-500 to-teal-500 hover:from-sky-400 hover:to-teal-400 text-white rounded-xl shadow-md shadow-sky-500/20 active:scale-95 transition flex items-center gap-1.5">
                                    <i class="fa-solid fa-bolt text-yellow-300"></i> 1-Click Tailor & Apply
                                </button>
                            </div>
                        </div>
                    `;
                }

                container.appendChild(card);
            });
        }

        function openDetailsModal(jobId) {
            if (!rawData) return;
            let job = null;
            const allLists = [
                rawData.today_jobs, rawData.recommended_jobs, rawData.fresh_jobs, rawData.remote_jobs,
                rawData.big_tech_jobs, rawData.unicorn_jobs, rawData.startup_jobs, rawData.it_services_jobs,
                rawData.tier1_jobs, rawData.tier2_jobs, rawData.all_shortlisted, rawData.applied_jobs
            ];
            for (const list of allLists) {
                if (list) {
                    const found = list.find(x => x.job_id === jobId);
                    if (found) { job = found; break; }
                }
            }
            if (!job) return;

            // Badges
            const badgesEl = document.getElementById('modal-badges');
            badgesEl.innerHTML = '';
            const todayStr = new Date().toISOString().slice(0, 10);
            if ((job.created_at || '').startsWith(todayStr)) {
                badgesEl.innerHTML += `<span class="text-[10px] px-2 py-0.5 rounded-md bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-semibold flex items-center gap-1"><i class="fa-solid fa-sparkles text-[9px]"></i> Discovered Today</span>`;
            }
            if (job.tier) {
                const cat = (job.tier || '').toLowerCase();
                if (cat.includes('big tech') || cat.includes('mnc')) {
                    badgesEl.innerHTML += `<span class="text-[10px] px-2 py-0.5 rounded-md bg-cyan-500/10 text-cyan-300 border border-cyan-500/20 font-semibold flex items-center gap-1"><i class="fa-solid fa-building-columns text-[9px]"></i> Big Tech & MNC</span>`;
                } else if (cat.includes('unicorn') || cat.includes('giant')) {
                    badgesEl.innerHTML += `<span class="text-[10px] px-2 py-0.5 rounded-md bg-amber-500/10 text-amber-300 border border-amber-500/20 font-semibold flex items-center gap-1"><i class="fa-solid fa-wand-magic-sparkles text-[9px]"></i> Unicorn</span>`;
                } else if (cat.includes('startup')) {
                    badgesEl.innerHTML += `<span class="text-[10px] px-2 py-0.5 rounded-md bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 font-semibold flex items-center gap-1"><i class="fa-solid fa-rocket text-[9px]"></i> Startup</span>`;
                } else if (cat.includes('it services') || cat.includes('service') || cat.includes('consult')) {
                    badgesEl.innerHTML += `<span class="text-[10px] px-2 py-0.5 rounded-md bg-slate-500/15 text-slate-300 border border-slate-500/30 font-semibold flex items-center gap-1"><i class="fa-solid fa-building text-[9px]"></i> IT Services</span>`;
                } else {
                    badgesEl.innerHTML += `<span class="text-[10px] px-2 py-0.5 rounded-md bg-[#181b28] text-slate-300 border border-[#24283b] font-medium">${job.tier.split(':')[0]}</span>`;
                }
            }
            if (job.is_remote_verified) {
                badgesEl.innerHTML += `<span class="text-[10px] px-2 py-0.5 rounded-md bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 font-medium flex items-center gap-1"><i class="fa-solid fa-globe text-[9px]"></i> Remote</span>`;
            }
            if (job.platform) {
                badgesEl.innerHTML += `<span class="text-[10px] px-2 py-0.5 rounded-md bg-sky-500/10 text-sky-400 border border-sky-500/20 font-mono">${job.platform}</span>`;
            }
            const datePosted = job.date_posted && job.date_posted !== 'nan' ? job.date_posted : 'Recent';
            badgesEl.innerHTML += `<span class="text-[10px] text-slate-400 flex items-center gap-1"><i class="fa-regular fa-clock"></i> ${datePosted}</span>`;

            // Title & Subtitle
            document.getElementById('modal-title').innerText = job.title;
            document.getElementById('modal-subtitle').innerText = `${job.company} • ${job.location || 'Remote/India'}`;

            // Score & Match section
            const scoreEl = document.getElementById('modal-score-badge');
            scoreEl.innerText = `${job.score || 0}% Match`;
            scoreEl.className = (job.score >= 90)
                ? 'px-2.5 py-0.5 rounded-md text-xs font-extrabold border text-emerald-400 bg-emerald-500/10 border-emerald-500/20'
                : (job.score >= 80)
                ? 'px-2.5 py-0.5 rounded-md text-xs font-extrabold border text-sky-400 bg-sky-500/10 border-sky-500/20'
                : 'px-2.5 py-0.5 rounded-md text-xs font-extrabold border text-amber-400 bg-amber-500/10 border-amber-500/20';

            const matchSection = document.getElementById('modal-match-section');
            const notesEl = document.getElementById('modal-matching-notes');
            if (job.matching_notes || job.evidence) {
                matchSection.classList.remove('hidden');
                notesEl.innerHTML = (job.matching_notes ? `<p class="mb-1">${escapeHtml(job.matching_notes)}</p>` : '') +
                    (job.evidence ? `<p class="text-slate-400 text-[11px]"><b class="text-slate-300">Key Evidence:</b> ${escapeHtml(job.evidence)}</p>` : '');
            } else {
                matchSection.classList.add('hidden');
            }

            // Skills Chips
            const skillsChips = document.getElementById('modal-skills-chips');
            skillsChips.innerHTML = '';
            let skillsList = [];
            if (job.skills) {
                try {
                    if (job.skills.startsWith('[') && job.skills.endsWith(']')) {
                        skillsList = JSON.parse(job.skills.replace(/'/g, '"'));
                    } else {
                        skillsList = job.skills.split(',').map(s => s.trim());
                    }
                } catch (_) {
                    skillsList = job.skills.split(',').map(s => s.trim());
                }
            }
            if (skillsList.length > 0) {
                document.getElementById('modal-skills-section').classList.remove('hidden');
                skillsList.forEach(skill => {
                    if (skill) {
                        const chip = document.createElement('span');
                        chip.className = "text-[11px] px-2.5 py-1 rounded-md bg-[#181b28] text-slate-200 border border-[#24283b] font-mono";
                        chip.innerText = skill;
                        skillsChips.appendChild(chip);
                    }
                });
            } else {
                document.getElementById('modal-skills-section').classList.add('hidden');
            }

            // Full description
            const descEl = document.getElementById('modal-description');
            descEl.innerText = job.description || 'No detailed description available for this posting.';

            // Footer actions
            const listingUrl = (job.job_url_direct || job.job_url || '').trim();
            const listingLink = document.getElementById('modal-listing-link');
            if (listingUrl) {
                listingLink.href = listingUrl;
                listingLink.classList.remove('hidden');
            } else {
                listingLink.classList.add('hidden');
            }

            currentModalPdfPath = job.tailored_resume_pdf_path || '';
            const pdfLink = document.getElementById('modal-pdf-link');
            const revealBtn = document.getElementById('modal-reveal-btn');
            if (currentModalPdfPath) {
                pdfLink.href = `/pdf?path=${encodeURIComponent(currentModalPdfPath)}`;
                pdfLink.classList.remove('hidden');
                if (revealBtn) revealBtn.classList.remove('hidden');
            } else {
                pdfLink.classList.add('hidden');
                if (revealBtn) revealBtn.classList.add('hidden');
            }

            const dismissBtn = document.getElementById('modal-dismiss-btn');
            dismissBtn.onclick = () => dismissJob(job.job_id);

            const markAppliedBtn = document.getElementById('modal-mark-applied-btn');
            if (markAppliedBtn) {
                if (job.status === 'applied') {
                    markAppliedBtn.classList.add('hidden');
                } else {
                    markAppliedBtn.classList.remove('hidden');
                    markAppliedBtn.onclick = () => markAppliedDirect(job.job_id, markAppliedBtn);
                }
            }

            const applyBtn = document.getElementById('modal-apply-btn');
            applyBtn.onclick = () => applyJob(job.job_id, applyBtn);

            const modal = document.getElementById('job-details-modal');
            modal.showModal();
        }

        function closeDetailsModal() {
            const modal = document.getElementById('job-details-modal');
            if (modal && modal.open) modal.close();
        }

        function openCustomJobModal() {
            const modal = document.getElementById('custom-job-modal');
            document.getElementById('custom-url-input').value = '';
            document.getElementById('custom-text-input').value = '';
            const pdfInput = document.getElementById('custom-pdf-input');
            if (pdfInput) pdfInput.value = '';
            document.getElementById('custom-job-progress').classList.add('hidden');
            document.getElementById('custom-submit-btn').disabled = false;
            modal.showModal();
        }

        function closeCustomJobModal() {
            const modal = document.getElementById('custom-job-modal');
            if (modal && modal.open) modal.close();
        }

        async function pasteCustomUrl() {
            try {
                const text = await navigator.clipboard.readText();
                if (text) {
                    document.getElementById('custom-url-input').value = text.trim();
                }
            } catch (_) {
                showToast('Please paste the URL directly into the field.', true);
            }
        }

        async function submitCustomJob(e) {
            if (e) e.preventDefault();
            const url = document.getElementById('custom-url-input').value.trim();
            const text = document.getElementById('custom-text-input').value.trim();
            const pdfInput = document.getElementById('custom-pdf-input');
            const pdfFile = (pdfInput && pdfInput.files) ? pdfInput.files[0] : null;

            if (!url && !text && !pdfFile) {
                showToast('Please enter a job URL, select a PDF, or enter raw description.', true);
                return;
            }

            const progress = document.getElementById('custom-job-progress');
            const statusText = document.getElementById('custom-job-status-text');
            const submitBtn = document.getElementById('custom-submit-btn');

            progress.classList.remove('hidden');
            submitBtn.disabled = true;

            if (pdfFile) {
                statusText.innerText = `Ingesting ${pdfFile.name} & screening with AI...`;
                const reader = new FileReader();
                reader.onload = async () => {
                    const base64Data = reader.result.split(',')[1];
                    try {
                        const res = await fetch('/api/upload-jd-pdf', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                filename: pdfFile.name,
                                pdf_base64: base64Data,
                                profile: currentProfile,
                            })
                        });
                        const data = await res.json();
                        if (data.success && data.job_id) {
                            statusText.innerText = 'Success! Opening application workflow...';
                            setTimeout(() => {
                                closeCustomJobModal();
                                window.location.href = '/apply?id=' + encodeURIComponent(data.job_id) + (currentProfile ? '&profile=' + encodeURIComponent(currentProfile) : '');
                            }, 600);
                        } else {
                            progress.classList.add('hidden');
                            submitBtn.disabled = false;
                            showToast('Failed to add job: ' + (data.error || 'Unknown error'), true);
                        }
                    } catch (err) {
                        progress.classList.add('hidden');
                        submitBtn.disabled = false;
                        showToast('Failed to process PDF: ' + err, true);
                    }
                };
                reader.readAsDataURL(pdfFile);
                return;
            }

            statusText.innerText = 'Extracting job posting & screening with AI...';

            try {
                const res = await fetch('/api/custom', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: url || null, text: text || null })
                });
                const data = await res.json();
                if (data.success && data.job_id) {
                    statusText.innerText = 'Success! Opening tailored application workflow...';
                    setTimeout(() => {
                        closeCustomJobModal();
                        window.location.href = '/apply?id=' + encodeURIComponent(data.job_id) + (currentProfile ? '&profile=' + encodeURIComponent(currentProfile) : '');
                    }, 600);
                } else {
                    progress.classList.add('hidden');
                    submitBtn.disabled = false;
                    showToast('Failed to add job: ' + (data.error || 'Unknown error'), true);
                }
            } catch (err) {
                progress.classList.add('hidden');
                submitBtn.disabled = false;
                showToast('Failed to process custom link: ' + err, true);
            }
        }

        function handlePdfDragOver(e) {
            e.preventDefault();
            e.stopPropagation();
            const dropZone = document.getElementById('pdf-drop-zone');
            if (dropZone) dropZone.classList.add('border-sky-500', 'bg-[#121626]');
        }

        function handlePdfDragLeave(e) {
            e.preventDefault();
            e.stopPropagation();
            const dropZone = document.getElementById('pdf-drop-zone');
            if (dropZone) dropZone.classList.remove('border-sky-500', 'bg-[#121626]');
        }

        function handlePdfDrop(e) {
            e.preventDefault();
            e.stopPropagation();
            const dropZone = document.getElementById('pdf-drop-zone');
            if (dropZone) dropZone.classList.remove('border-sky-500', 'bg-[#121626]');
            if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                handlePdfFiles(e.dataTransfer.files);
            }
        }

        function formatBytes(bytes) {
            if (!bytes || bytes === 0) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
        }

        async function handlePdfFiles(fileList) {
            if (!fileList || fileList.length === 0) return;
            const files = Array.from(fileList);
            const queue = document.getElementById('pdf-processing-queue');
            if (queue) queue.classList.remove('hidden');

            for (const file of files) {
                if (!file.name.toLowerCase().endsWith('.pdf') && file.type !== 'application/pdf') {
                    showToast(`${file.name} is not a PDF file`, true);
                    continue;
                }
                uploadSinglePdf(file);
            }
        }

        function uploadSinglePdf(file) {
            const queue = document.getElementById('pdf-processing-queue');
            const itemId = 'pdf-item-' + Math.random().toString(36).substring(2, 9);

            const card = document.createElement('div');
            card.id = itemId;
            card.className = 'p-3.5 bg-[#0a0c14] border border-[#1e2233] rounded-xl flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-sm transition hover:border-[#282d42]';
            card.innerHTML = `
                <div class="flex items-center gap-3 min-w-0">
                    <div class="w-8 h-8 rounded-lg bg-rose-500/10 text-rose-400 border border-rose-500/20 flex items-center justify-center shrink-0">
                        <i class="fa-solid fa-file-pdf"></i>
                    </div>
                    <div class="min-w-0">
                        <div class="text-xs font-bold text-white truncate">${escapeHtml(file.name)}</div>
                        <div class="text-[11px] text-slate-400 flex items-center gap-2">
                            <span>${formatBytes(file.size)}</span>
                            <span>•</span>
                            <span id="${itemId}-status" class="text-sky-400 font-medium flex items-center gap-1.5">
                                <i class="fa-solid fa-circle-notch fa-spin text-[10px]"></i> Reading PDF & screening with AI...
                            </span>
                        </div>
                    </div>
                </div>
                <div id="${itemId}-actions" class="flex items-center gap-2 shrink-0"></div>
            `;
            queue.prepend(card);

            const reader = new FileReader();
            reader.onload = async () => {
                const base64Data = reader.result.split(',')[1];
                try {
                    const res = await fetch('/api/upload-jd-pdf', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            filename: file.name,
                            pdf_base64: base64Data,
                            profile: currentProfile,
                        })
                    });
                    const data = await res.json();
                    if (!res.ok || !data.success) {
                        throw new Error(data.error || 'Server error ingesting PDF');
                    }

                    const statusEl = document.getElementById(`${itemId}-status`);
                    if (data.status === 'pending' && data.task_id) {
                        if (statusEl) {
                            statusEl.className = 'text-amber-400 font-medium flex items-center gap-1.5';
                            statusEl.innerHTML = `<i class="fa-solid fa-gear fa-spin text-[10px]"></i> Generating 1-page ATS resume for <b>${escapeHtml(data.company || 'Company')}</b>...`;
                        }
                        pollPdfTailorStatus(data.task_id, itemId, data);
                    } else if (data.resume_pdf_path) {
                        onPdfTailorSuccess(itemId, data);
                    }
                } catch (err) {
                    const statusEl = document.getElementById(`${itemId}-status`);
                    if (statusEl) {
                        statusEl.className = 'text-rose-400 font-medium flex items-center gap-1.5';
                        statusEl.innerHTML = `<i class="fa-solid fa-circle-exclamation text-[10px]"></i> Failed: ${escapeHtml(err.message || String(err))}`;
                    }
                    showToast(`Error processing ${file.name}: ${err.message}`, true);
                }
            };
            reader.readAsDataURL(file);
        }

        async function pollPdfTailorStatus(taskId, itemId, jobMeta) {
            const start = Date.now();
            const pollInterval = setInterval(async () => {
                try {
                    const elapsed = Math.round((Date.now() - start) / 1000);
                    if (elapsed > 180) {
                        clearInterval(pollInterval);
                        const statusEl = document.getElementById(`${itemId}-status`);
                        if (statusEl) {
                            statusEl.className = 'text-rose-400 font-medium';
                            statusEl.innerHTML = 'Tailoring timed out after 3 minutes';
                        }
                        return;
                    }

                    const r = await fetch('/api/apply-status?task_id=' + encodeURIComponent(taskId));
                    if (!r.ok) return;
                    const d = await r.json();
                    if (d.status === 'done' && d.success) {
                        clearInterval(pollInterval);
                        onPdfTailorSuccess(itemId, {
                            ...jobMeta,
                            resume_path: d.resume_path,
                            resume_pdf_path: d.resume_pdf_path,
                            title: d.title || jobMeta.title,
                            company: d.company || jobMeta.company,
                            job_id: d.job_id || jobMeta.job_id,
                        });
                    } else if (d.status === 'error' || d.error) {
                        clearInterval(pollInterval);
                        const statusEl = document.getElementById(`${itemId}-status`);
                        if (statusEl) {
                            statusEl.className = 'text-rose-400 font-medium';
                            statusEl.innerHTML = `Tailoring failed: ${escapeHtml(d.error || 'Unknown error')}`;
                        }
                    }
                } catch (_) {}
            }, 1500);
        }

        function onPdfTailorSuccess(itemId, result) {
            const statusEl = document.getElementById(`${itemId}-status`);
            const actionsEl = document.getElementById(`${itemId}-actions`);
            const title = result.title || 'Role';
            const company = result.company || 'Company';
            const pdfPath = result.resume_pdf_path || '';
            const jobId = result.job_id || '';

            if (statusEl) {
                statusEl.className = 'text-emerald-400 font-semibold flex items-center gap-1.5';
                statusEl.innerHTML = `<i class="fa-solid fa-circle-check text-[10px]"></i> 1-Page Resume Ready • <b>${escapeHtml(title)}</b> @ <b>${escapeHtml(company)}</b>`;
            }

            if (actionsEl) {
                actionsEl.innerHTML = `
                    ${pdfPath ? `
                        <a href="/pdf?path=${encodeURIComponent(pdfPath)}" target="_blank" class="px-3 py-1.5 bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-400 hover:to-indigo-500 text-white font-semibold rounded-xl text-xs flex items-center gap-1.5 transition shadow-sm">
                            <i class="fa-solid fa-file-arrow-down text-[10px]"></i> Open Resume PDF
                        </a>
                        <button onclick="revealInFinder('${escapeHtml(pdfPath)}')" class="px-2.5 py-1.5 bg-[#181b28] hover:bg-[#222638] text-slate-300 rounded-xl border border-[#24283b] text-xs flex items-center gap-1 transition" title="Reveal in Finder">
                            <i class="fa-regular fa-folder-open text-[11px]"></i>
                        </button>
                    ` : ''}
                    ${jobId ? `
                        <button onclick="openDetailsModal('${escapeHtml(jobId)}')" class="px-2.5 py-1.5 bg-[#181b28] hover:bg-[#222638] text-slate-300 rounded-xl border border-[#24283b] text-xs flex items-center gap-1 transition" title="View Job Details">
                            <i class="fa-solid fa-eye text-[11px]"></i> Details
                        </button>
                    ` : ''}
                `;
            }

            showToast(`Resume generated for ${company}!`);
            fetchJobs();
        }

        function askApplicationOutcome(taskId, jobId, jobTitle, company) {
            return new Promise((resolve) => {
                const modal = document.getElementById('apply-outcome-modal');
                const titleEl = document.getElementById('outcome-modal-title');
                const subEl = document.getElementById('outcome-modal-subtitle');
                if (titleEl) titleEl.textContent = 'Application Submitted?';
                if (subEl) subEl.textContent = `${jobTitle || 'Role'} at ${company || 'Company'}: did you submit your application?`;

                const appliedBtn = document.getElementById('outcome-applied-btn');
                const skipBtn = document.getElementById('outcome-skip-btn');
                const expiredBtn = document.getElementById('outcome-expired-btn');

                const cleanup = (outcome) => {
                    appliedBtn.onclick = null;
                    skipBtn.onclick = null;
                    expiredBtn.onclick = null;
                    if (modal && modal.open) modal.close();
                    resolve(outcome);
                };

                appliedBtn.onclick = () => cleanup('applied');
                skipBtn.onclick = () => cleanup('skipped');
                expiredBtn.onclick = () => cleanup('expired');

                modal.showModal();
            });
        }

        async function markAppliedDirect(jobId, btn) {
            if (!confirm('Mark this job as Applied and sync to Notion tracker?')) return;
            const originalText = btn ? btn.innerHTML : '';
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Saving...';
            }
            try {
                const res = await fetch('/api/mark-applied', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ job_id: jobId })
                });
                const data = await res.json();
                if (res.ok && data.success) {
                    showToast('✓ Job marked as applied & syncing to Notion!');
                    fetchJobs();
                    closeDetailsModal();
                } else {
                    showToast('Failed to mark applied: ' + (data.error || 'Unknown error'), true);
                    if (btn) {
                        btn.disabled = false;
                        btn.innerHTML = originalText;
                    }
                }
            } catch (e) {
                showToast('Error marking applied: ' + e.message, true);
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = originalText;
                }
            }
        }

        async function applyJob(jobId, btn) {
            const originalText = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i> Starting...`;

            try {
                // 1. Kick off the tailoring task (returns 202 immediately)
                const res = await fetch('/api/apply', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ job_id: jobId, profile: currentProfile })
                });
                const initData = await res.json();
                if (res.status === 404 || res.status === 400) {
                    showToast('Error: ' + (initData.error || 'Unknown error'), true);
                    btn.disabled = false;
                    btn.innerHTML = originalText;
                    return;
                }
                const taskId = initData.task_id;
                if (!taskId) {
                    showToast('Error: No task ID returned from server', true);
                    btn.disabled = false;
                    btn.innerHTML = originalText;
                    return;
                }

                // 2. Poll /api/apply-status until done or error (max 3 minutes)
                const startTime = Date.now();
                const maxWaitMs = 180000;
                while (true) {
                    const elapsed = Math.round((Date.now() - startTime) / 1000);
                    btn.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i> Tailoring Resume... ${elapsed}s`;

                    if (Date.now() - startTime > maxWaitMs) {
                        showToast('Timed out waiting for tailored resume. Check terminal for progress.', true);
                        btn.disabled = false;
                        btn.innerHTML = originalText;
                        return;
                    }

                    await new Promise(r => setTimeout(r, 3000));

                    const pollRes = await fetch('/api/apply-status?task_id=' + encodeURIComponent(taskId));
                    if (pollRes.status === 404) {
                        showToast('Error: Task not found or expired on server', true);
                        btn.disabled = false;
                        btn.innerHTML = originalText;
                        return;
                    }
                    const pollData = await pollRes.json();

                    if (pollData.status === 'done' && pollData.success) {
                        if (pollData.resume_pdf_path) {
                            try {
                                await navigator.clipboard.writeText(pollData.resume_pdf_path);
                            } catch (_) {}
                            window.open('/pdf?path=' + encodeURIComponent(pollData.resume_pdf_path), '_blank');
                        }
                        let jobInfo = null;
                        if (rawData && rawData.all_shortlisted) {
                            jobInfo = rawData.all_shortlisted.find(x => x.job_id === jobId);
                        }
                        const outcome = await askApplicationOutcome(taskId, jobId, jobInfo ? jobInfo.title : '', jobInfo ? jobInfo.company : '');
                        const confirmRes = await fetch('/api/confirm-application', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ task_id: taskId, job_id: jobId, outcome })
                        });
                        const confirmData = await confirmRes.json();
                        if (!confirmRes.ok) {
                            showToast('Could not save application status: ' + (confirmData.error || 'Unknown error'), true);
                            btn.disabled = false;
                            btn.innerHTML = originalText;
                            return;
                        }
                        showToast(outcome === 'applied' ? '✓ Marked as applied & syncing to Notion!' : outcome === 'expired' ? 'Marked as expired / rejected.' : 'Kept in shortlist.');
                        fetchJobs();
                        closeDetailsModal();
                        return;
                    } else if (pollData.status === 'error' || pollData.error) {
                        showToast('Error: ' + (pollData.error || 'Failed to apply'), true);
                        btn.disabled = false;
                        btn.innerHTML = originalText;
                        return;
                    }
                    // status === 'pending' → keep polling
                }
            } catch (e) {
                showToast('Failed to execute apply: ' + e, true);
                btn.disabled = false;
                btn.innerHTML = originalText;
            }
        }


        async function dismissJob(jobId) {
            let job = null;
            if (rawData) {
                const allLists = [rawData.today_jobs, rawData.recommended_jobs, rawData.fresh_jobs, rawData.remote_jobs, rawData.tier1_jobs, rawData.tier2_jobs, rawData.all_shortlisted];
                for (const list of allLists) {
                    if (list) {
                        const found = list.find(x => x.job_id === jobId);
                        if (found) { job = found; break; }
                    }
                }
            }
            const company = job ? job.company : 'Job';

            try {
                const res = await fetch('/api/dismiss', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ job_id: jobId })
                });
                const data = await res.json();
                if (data.success) {
                    const card = document.getElementById('job-' + jobId);
                    if (card) card.remove();

                    if (rawData) {
                        const allLists = [rawData.today_jobs, rawData.recommended_jobs, rawData.fresh_jobs, rawData.remote_jobs, rawData.tier1_jobs, rawData.tier2_jobs, rawData.all_shortlisted];
                        for (const list of allLists) {
                            if (list) {
                                const idx = list.findIndex(x => x.job_id === jobId);
                                if (idx !== -1) list.splice(idx, 1);
                            }
                        }
                        if (rawData.stats) {
                            rawData.stats.total_shortlisted = Math.max(0, rawData.stats.total_shortlisted - 1);
                            if (rawData.today_jobs) rawData.stats.discovered_today = rawData.today_jobs.length;
                            renderMetrics();
                        }
                    }
                    closeDetailsModal();
                    showToast(`Dismissed ${company}`, false, () => restoreJob(jobId));
                }
            } catch (e) {
                showToast('Failed to dismiss: ' + e, true);
            }
        }

        async function restoreJob(jobId) {
            try {
                const res = await fetch('/api/restore', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ job_id: jobId })
                });
                const data = await res.json();
                if (data.success) {
                    showToast('Job restored to shortlist!');
                    await fetchJobs();
                } else {
                    showToast('Failed to restore: ' + (data.error || 'Unknown error'), true);
                }
            } catch (e) {
                showToast('Failed to restore job: ' + e, true);
            }
        }

        async function archiveStaleJobs() {
            if (!confirm('Archive unapplied shortlisted jobs older than 7 days?')) return;
            try {
                const res = await fetch('/api/archive-stale', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ days: 7 })
                });
                const data = await res.json();
                showToast(`Archived ${data.archived_count} stale listings.`);
                fetchJobs();
            } catch (e) {
                showToast('Failed to archive: ' + e, true);
            }
        }

        // Setup Light Dismiss for Native Dialogs
        document.addEventListener('DOMContentLoaded', () => {
            ['job-details-modal', 'custom-job-modal'].forEach(id => {
                const d = document.getElementById(id);
                if (d) {
                    d.addEventListener('click', (e) => {
                        const rect = d.getBoundingClientRect();
                        const inDialog = (
                            rect.top <= e.clientY && e.clientY <= rect.top + rect.height &&
                            rect.left <= e.clientX && e.clientX <= rect.left + rect.width
                        );
                        if (!inDialog) d.close();
                    });
                }
            });
        });

        // Initialize
        const pSel = document.getElementById('activeProfileSelect');
        if (pSel) pSel.value = currentProfile;
        updateCandidateBadges();
        fetchJobs();
    </script>
</body>
</html>
"""


class DashboardRequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
            return

        elif path == "/api/jobs":
            data = get_dashboard_data()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))
            return

        elif path == "/custom":
            query = urllib.parse.parse_qs(parsed.query)
            target_url = query.get("url", [""])[0]
            profile_name = query.get("profile", ["madhav"])[0]
            if not target_url:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"<h1>Error: Missing 'url' parameter</h1>")
                return

            import custom_job
            job_id = custom_job.ingest_custom_job(target_url)
            if not job_id:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"<h1>Error: Failed to ingest custom job link.</h1>")
                return

            # Redirect to /apply
            self.send_response(302)
            self.send_header("Location", f"/apply?id={job_id}&profile={profile_name}")
            self.end_headers()
            return

        elif path == "/apply":
            query = urllib.parse.parse_qs(parsed.query)
            job_id = query.get("id", [""])[0]
            profile_name = query.get("profile", ["madhav"])[0]
            if not job_id:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"<h1>Error: Missing 'id' parameter in apply link</h1>")
                return

            conn = db.get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
            job = cursor.fetchone()
            conn.close()

            if not job:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(f"<h1>Error: Job ID '{job_id}' not found in database.</h1>".encode("utf-8"))
                return

            # Kick off tailoring in a background thread immediately
            task_id = str(uuid.uuid4())
            with _apply_tasks_lock:
                _apply_tasks[task_id] = {"status": "pending", "result": None, "error": None}

            threading.Thread(target=_run_tailor_worker, args=(task_id, job_id, job, profile_name), daemon=True).start()

            # Serve a self-polling "Generating..." page immediately
            loading_html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Tailoring Resume — {job['company']}</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-950 text-slate-100 flex items-center justify-center min-h-screen p-6">
    <div id="card" class="max-w-lg w-full bg-slate-900 border border-slate-800 rounded-2xl p-8 text-center space-y-6 shadow-2xl">
        <div id="icon" class="w-16 h-16 bg-sky-500/10 text-sky-400 border border-sky-500/20 rounded-full flex items-center justify-center mx-auto text-3xl animate-spin">
            ⚙
        </div>
        <div>
            <h1 class="text-2xl font-bold text-white">Tailoring Your Resume...</h1>
            <p class="text-slate-400 text-sm mt-1">Generating materials for <b>{job['title']}</b> at <b>{job['company']}</b></p>
        </div>
        <p id="elapsed" class="text-slate-500 text-xs">Elapsed: 0s — this usually takes 10–30 seconds</p>
        <p id="errmsg" class="text-red-400 text-sm hidden"></p>
    </div>
    <script>
        const taskId = {json.dumps(task_id)};
        const start = Date.now();
        const timer = setInterval(() => {{
            const s = Math.round((Date.now() - start) / 1000);
            const el = document.getElementById('elapsed');
            if (s > 90) {{
                el.innerHTML = `Elapsed: ${{s}}s — <span class="text-amber-400">Taking longer than usual.</span> <a href="/" class="underline text-sky-400 hover:text-sky-300 ml-1">Return to Dashboard</a>`;
            }} else {{
                el.textContent = `Elapsed: ${{s}}s — this usually takes 10–30 seconds`;
            }}
        }}, 1000);

        async function poll() {{
            try {{
                const elapsedSec = Math.round((Date.now() - start) / 1000);
                if (elapsedSec > 180) {{
                    clearInterval(timer);
                    document.getElementById('icon').textContent = '✕';
                    document.getElementById('icon').className = 'w-16 h-16 bg-red-500/10 text-red-400 border border-red-500/20 rounded-full flex items-center justify-center mx-auto text-3xl';
                    document.getElementById('errmsg').innerHTML = 'Tailoring timed out after 3 minutes.<br><a href="/" class="underline text-sky-400 hover:text-sky-300 mt-2 inline-block">Return to Dashboard</a>';
                    document.getElementById('errmsg').classList.remove('hidden');
                    return;
                }}
                const r = await fetch('/api/apply-status?task_id=' + encodeURIComponent(taskId));
                if (r.status === 404) {{
                    clearInterval(timer);
                    document.getElementById('icon').textContent = '✕';
                    document.getElementById('icon').className = 'w-16 h-16 bg-red-500/10 text-red-400 border border-red-500/20 rounded-full flex items-center justify-center mx-auto text-3xl';
                    document.getElementById('errmsg').textContent = 'Error: Task not found or expired on server.';
                    document.getElementById('errmsg').classList.remove('hidden');
                    document.getElementById('elapsed').textContent = '';
                    return;
                }}
                const d = await r.json();
                if (d.status === 'done' && d.success) {{
                    clearInterval(timer);
                    const pdfPath = d.resume_pdf_path || '';
                    const targetUrl = d.url || '';
                    document.getElementById('icon').textContent = '✓';
                    document.getElementById('icon').className = 'w-16 h-16 bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded-full flex items-center justify-center mx-auto text-3xl';
                    document.getElementById('card').innerHTML = `
                        <div class="w-16 h-16 bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded-full flex items-center justify-center mx-auto text-3xl">✓</div>
                        <div>
                            <h1 class="text-2xl font-bold text-white">Application Materials Ready!</h1>
                            <p class="text-slate-400 text-sm mt-1">Materials generated for <b>{job['title']}</b> at <b>{job['company']}</b></p>
                        </div>
                        <div class="bg-slate-950 p-4 rounded-xl text-left text-xs space-y-2 border border-slate-800 text-slate-300">
                            <div><b>Target URL Opened:</b> <a href="${{targetUrl}}" target="_blank" class="text-sky-400 underline truncate block">${{targetUrl || '(none)'}}</a></div>
                            <div id="status-line"><b>Status:</b> <span id="status-badge" class="text-amber-400 font-semibold">Ready for submission</span></div>
                        </div>
                        <div id="confirm-box" class="space-y-2 pt-2">
                            <p class="text-xs text-slate-400 font-medium">Did you submit your application on the company portal?</p>
                            <div class="flex flex-col sm:flex-row items-center justify-center gap-2">
                                <button onclick="confirmOutcome('applied')" class="w-full sm:w-auto px-5 py-2.5 bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-400 hover:to-teal-500 text-white font-bold rounded-xl text-xs transition shadow-lg shadow-emerald-500/20">
                                    ✓ Yes, Mark as Applied (Sync to Notion)
                                </button>
                                <button onclick="confirmOutcome('skipped')" class="w-full sm:w-auto px-4 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-300 font-medium rounded-xl text-xs transition border border-slate-700">
                                    Keep in Shortlist
                                </button>
                                <button onclick="confirmOutcome('expired')" class="w-full sm:w-auto px-3 py-2.5 text-slate-500 hover:text-rose-400 text-xs transition">
                                    Expired / Closed
                                </button>
                            </div>
                        </div>
                        <div class="flex items-center justify-center gap-3 pt-2">
                            ${{pdfPath ? `<a href="/pdf?path=${{encodeURIComponent(pdfPath)}}" target="_blank" class="px-5 py-2.5 bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-400 hover:to-indigo-500 text-white font-medium rounded-xl text-sm transition shadow-lg shadow-sky-500/20">📄 Open Tailored Resume PDF</a>` : ''}}
                            <a href="/" class="px-5 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-300 font-medium rounded-xl text-sm transition border border-slate-700">← Return to Dashboard</a>
                        </div>
                    `;
                }} else if (d.status === 'error' || d.error) {{
                    clearInterval(timer);
                    document.getElementById('icon').textContent = '✕';
                    document.getElementById('icon').className = 'w-16 h-16 bg-red-500/10 text-red-400 border border-red-500/20 rounded-full flex items-center justify-center mx-auto text-3xl';
                    document.getElementById('errmsg').textContent = 'Error: ' + (d.error || 'Unknown error');
                    document.getElementById('errmsg').classList.remove('hidden');
                    document.getElementById('elapsed').textContent = '';
                }} else {{
                    setTimeout(poll, 3000);
                }}
            }} catch(e) {{
                setTimeout(poll, 3000);
            }}
        }}

        async function confirmOutcome(outcome) {{
            try {{
                const confirmResponse = await fetch('/api/confirm-application', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ task_id: taskId, job_id: {json.dumps(job_id)}, outcome }})
                }});
                const confirmation = await confirmResponse.json();
                if (!confirmResponse.ok) throw new Error(confirmation.error || 'Could not save application status');
                const badge = document.getElementById('status-badge');
                if (badge) {{
                    badge.textContent = outcome === 'applied' ? 'Marked as Applied & Syncing to Notion' : outcome === 'expired' ? 'Marked as Expired / Rejected' : 'Kept as Shortlisted';
                    badge.className = outcome === 'applied' ? 'text-emerald-400 font-bold' : outcome === 'expired' ? 'text-rose-400 font-bold' : 'text-slate-400 font-bold';
                }}
                const box = document.getElementById('confirm-box');
                if (box) {{
                    box.innerHTML = `<div class="p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-xl text-xs text-emerald-400 font-semibold">✓ Status updated successfully! You can return to the dashboard.</div>`;
                }}
            }} catch(e) {{
                alert('Error updating status: ' + e.message);
            }}
        }}

        setTimeout(poll, 3000);
    </script>
</body>
</html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(loading_html.encode("utf-8"))
            return


        elif path == "/dismiss":
            query = urllib.parse.parse_qs(parsed.query)
            job_id = query.get("id", [""])[0]
            if not job_id:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"<h1>Error: Missing 'id' parameter in dismiss link</h1>")
                return

            conn = db.get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
            job = cursor.fetchone()
            if job:
                db.mark_as_rejected(job_id)
            conn.close()

            # Regenerate markdown and PDF dashboard in background
            try:
                import dashboard
                threading.Thread(target=dashboard.generate_dashboard).start()
            except Exception:
                pass

            company_name = job["company"] if job else "Unknown Company"
            job_title = job["title"] if job else job_id

            dismiss_html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Job Dismissed — {company_name}</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-950 text-slate-100 flex items-center justify-center min-h-screen p-6">
    <div class="max-w-lg w-full bg-slate-900 border border-slate-800 rounded-2xl p-8 text-center space-y-6 shadow-2xl">
        <div class="w-16 h-16 bg-rose-500/10 text-rose-400 border border-rose-500/20 rounded-full flex items-center justify-center mx-auto text-2xl font-bold">
            ✕
        </div>
        <div>
            <h1 class="text-2xl font-bold text-white">Listing Dismissed</h1>
            <p class="text-slate-400 text-sm mt-1"><b>{job_title}</b> at <b>{company_name}</b> has been removed from your active shortlist.</p>
        </div>
        <div class="bg-slate-950 p-4 rounded-xl text-left text-xs space-y-1 border border-slate-800 text-slate-400">
            <div><b>Job ID:</b> <code class="text-rose-400">{job_id}</code></div>
            <div><b>Status:</b> Marked as <span class="text-rose-400 font-semibold">Dismissed / Do Not Consider</span></div>
        </div>
        <div class="flex items-center justify-center gap-3">
            <a href="/" class="px-5 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-300 font-medium rounded-xl text-sm transition border border-slate-700">
                ← Return to Dashboard
            </a>
        </div>
    </div>
</body>
</html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(dismiss_html.encode("utf-8"))
            return

        elif path == "/pdf":
            query = urllib.parse.parse_qs(parsed.query)
            pdf_path = query.get("path", [""])[0]
            if not pdf_path:
                self.send_response(400)
                self.end_headers()
                return

            abs_path = os.path.abspath(pdf_path)
            if not is_safe_tailored_path(abs_path) or not abs_path.endswith(".pdf"):
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Access denied: outside tailored directory"}).encode("utf-8"))
                return

            if not os.path.isfile(abs_path):
                self.send_response(404)
                self.end_headers()
                return

            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", f'inline; filename="{os.path.basename(abs_path)}"')
            self.end_headers()
            with open(abs_path, "rb") as f:
                self.wfile.write(f.read())
            return

        elif path == "/api/apply-status":
            query = urllib.parse.parse_qs(parsed.query)
            task_id = query.get("task_id", [""])[0]
            with _apply_tasks_lock:
                task = _apply_tasks.get(task_id)
            if task is None:
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Unknown task_id"}).encode("utf-8"))
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            payload = {"status": task["status"]}
            if task["status"] == "done":
                payload["success"] = True
                payload.update(task["result"])
            elif task["status"] == "error":
                payload["error"] = task["error"]
            self.wfile.write(json.dumps(payload).encode("utf-8"))
            return

        elif path == "/api/profiles":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(profiles.list_profiles()).encode("utf-8"))
            return

        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len) if content_len > 0 else b"{}"
        try:
            params = json.loads(body.decode("utf-8"))
        except Exception:
            params = {}

        if path == "/api/apply":
            job_id = params.get("job_id")
            profile_name = params.get("profile", "madhav")
            if not job_id:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Missing job_id"}).encode("utf-8"))
                return

            # Validate job exists before spawning thread
            conn = db.get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
            job = cursor.fetchone()
            conn.close()

            if not job:
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Job not found"}).encode("utf-8"))
                return

            # Return 202 immediately — tailoring runs in background thread
            task_id = str(uuid.uuid4())
            with _apply_tasks_lock:
                _apply_tasks[task_id] = {"status": "pending", "result": None, "error": None}

            threading.Thread(target=_run_tailor_worker, args=(task_id, job_id, job, profile_name), daemon=True).start()

            self.send_response(202)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"task_id": task_id, "status": "pending"}).encode("utf-8"))
            return


        elif path == "/api/confirm-application":
            task_id = params.get("task_id")
            job_id = params.get("job_id")
            outcome = params.get("outcome")
            if not task_id or not job_id or not outcome:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "task_id, job_id, and outcome are required"}).encode("utf-8"))
                return
            try:
                result = finalize_application(task_id, job_id, outcome)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, **result}).encode("utf-8"))
            except ValueError as exc:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(exc)}).encode("utf-8"))
            return

        elif path == "/api/mark-applied":
            job_id = params.get("job_id")
            if not job_id:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "job_id is required"}).encode("utf-8"))
                return

            conn = db.get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT tailored_resume_path, tailored_cover_letter_path,
                       tailored_resume_pdf_path, tailored_cover_letter_pdf_path
                FROM jobs WHERE job_id = ?
            """, (job_id,))
            row = cursor.fetchone()
            conn.close()

            if not row:
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Job not found"}).encode("utf-8"))
                return

            db.mark_as_applied(
                job_id,
                row["tailored_resume_path"] if row else None,
                row["tailored_cover_letter_path"] if row else None,
                row["tailored_resume_pdf_path"] if row else None,
                row["tailored_cover_letter_pdf_path"] if row else None,
            )

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "job_id": job_id, "status": "applied"}).encode("utf-8"))
            return

        elif path == "/api/reveal":
            raw_path = params.get("path")
            if not raw_path:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Path required"}).encode("utf-8"))
                return

            abs_path = os.path.abspath(raw_path)
            if not is_safe_tailored_path(abs_path):
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Access denied: outside tailored directory"}).encode("utf-8"))
                return

            if not os.path.exists(abs_path):
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "File not found"}).encode("utf-8"))
                return

            if sys.platform == "darwin":
                try:
                    subprocess.run(["open", "-R", abs_path], check=False)
                except Exception:
                    pass
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
            return

        elif path == "/api/dismiss":
            job_id = params.get("job_id")
            if job_id:
                db.mark_as_rejected(job_id)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
                return

        elif path == "/api/restore":
            job_id = params.get("job_id")
            if not job_id:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Missing job_id"}).encode("utf-8"))
                return

            conn = db.get_db_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE jobs SET status = 'shortlisted' WHERE job_id = ?", (job_id,))
            conn.commit()
            conn.close()

            # Trigger background dashboard rebuild
            try:
                import dashboard
                threading.Thread(target=dashboard.generate_dashboard).start()
            except Exception:
                pass

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "job_id": job_id}).encode("utf-8"))
            return

        elif path == "/api/archive-stale":
            days = params.get("days", 7)
            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            conn = db.get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE jobs
            SET status = 'rejected'
            WHERE status = 'shortlisted' AND (created_at < ? OR created_at IS NULL)
            """, (cutoff,))
            count = cursor.rowcount
            conn.commit()
            conn.close()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "archived_count": count}).encode("utf-8"))
            return

        elif path == "/api/custom":
            custom_url = params.get("url")
            custom_text = params.get("text")
            if not custom_url and not custom_text:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Missing url or text"}).encode("utf-8"))
                return

            try:
                import custom_job
                job_id = custom_job.ingest_custom_job(custom_url, custom_text=custom_text)
                if not job_id:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Failed to parse and ingest job."}).encode("utf-8"))
                    return

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "job_id": job_id}).encode("utf-8"))
                return
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
                return

        elif path == "/api/upload-jd-pdf":
            filename = params.get("filename", "job_description.pdf")
            pdf_base64 = params.get("pdf_base64")
            profile_name = params.get("profile", "madhav")
            sync_mode = params.get("sync", False)

            if not pdf_base64:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Missing pdf_base64 parameter"}).encode("utf-8"))
                return

            import base64
            try:
                pdf_bytes = base64.b64decode(pdf_base64)
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"Invalid base64 payload: {e}"}).encode("utf-8"))
                return

            if len(pdf_bytes) > 25 * 1024 * 1024:
                self.send_response(413)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "File size exceeds 25MB limit"}).encode("utf-8"))
                return

            try:
                import custom_job
                job_id, job_row = custom_job.ingest_pdf_job(pdf_bytes, filename=filename)
                if not job_id:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Failed to parse and ingest PDF JD."}).encode("utf-8"))
                    return

                if sync_mode:
                    materials = tailor.tailor_materials(job_id, profile_name=profile_name)
                    if not materials:
                        raise ValueError("Failed to generate tailored materials")
                    resume_path, resume_pdf_path = materials[0], materials[1]
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "success": True,
                        "job_id": job_id,
                        "title": job_row.get("title", ""),
                        "company": job_row.get("company", ""),
                        "score": job_row.get("score", 0),
                        "resume_path": resume_path,
                        "resume_pdf_path": resume_pdf_path,
                        "pdf_url": f"/pdf?path={urllib.parse.quote(resume_pdf_path)}",
                    }).encode("utf-8"))
                    return

                # Async mode: dispatch to _run_tailor_worker and return task_id
                task_id = str(uuid.uuid4())
                with _apply_tasks_lock:
                    _apply_tasks[task_id] = {"status": "pending", "result": None, "error": None}

                threading.Thread(target=_run_tailor_worker, args=(task_id, job_id, job_row, profile_name), daemon=True).start()

                self.send_response(202)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": True,
                    "task_id": task_id,
                    "job_id": job_id,
                    "title": job_row.get("title", ""),
                    "company": job_row.get("company", ""),
                    "score": job_row.get("score", 0),
                    "status": "pending",
                }).encode("utf-8"))
                return

            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
                return

        self.send_response(404)
        self.end_headers()


def start_server(open_browser: bool = True):
    """Start local web dashboard server."""
    server_address = ("127.0.0.1", PORT)

    class _ReuseServer(socketserver.ThreadingTCPServer):
        allow_reuse_address = True

    httpd = _ReuseServer(server_address, DashboardRequestHandler)
    print(f"\n=======================================================")
    print(f"🚀 Job Hunter Interactive Dashboard running at:")
    print(f"   http://127.0.0.1:{PORT}")
    print(f"=======================================================\n")

    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down dashboard server.")
        httpd.server_close()


if __name__ == "__main__":
    start_server(open_browser=True)
