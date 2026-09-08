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
from notion_sync import derive_status_portal_url, map_platform
from screening import classify_company_tier, is_job_truly_remote

PORT = 8765
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def get_dashboard_data():
    db.init_db()
    conn = db.get_db_connection()
    cursor = conn.cursor()

    # Query all shortlisted jobs
    cursor.execute("""
    SELECT job_id, site, job_url, job_url_direct, title, company, location,
           date_posted, job_type, is_remote, skills, score, evidence,
           matching_notes, tailored_resume_pdf_path, created_at, status, description
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
    conn.close()

    # Filter out unverified agencies & enrich shortlisted
    valid_shortlisted = []
    for j in all_shortlisted:
        tier = classify_company_tier(j["company"])
        if not tier.startswith("Tier 3"):
            j["tier"] = tier
            j["apply_url"] = j["job_url_direct"] or j["job_url"]
            j["is_remote_verified"] = is_job_truly_remote(j)
            plat = map_platform(j["apply_url"], j.get("site", ""), j.get("company", ""))
            j["platform"] = plat
            j["status_portal_url"] = derive_status_portal_url(j["apply_url"], plat, j.get("company", ""), j.get("job_id", ""))
            valid_shortlisted.append(j)

    # Enrich applied jobs with platform & status tracking portal
    for j in applied:
        j["apply_url"] = j["job_url_direct"] or j["job_url"]
        plat = map_platform(j["apply_url"], j.get("site", ""), j.get("company", ""))
        j["platform"] = plat
        j["status_portal_url"] = derive_status_portal_url(j["apply_url"], plat, j.get("company", ""), j.get("job_id", ""))

    # Calculate 48h Freshness cutoff
    cutoff_48h = (datetime.now() - timedelta(hours=48)).strftime("%Y-%m-%d %H:%M:%S")
    cutoff_7d = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")

    fresh_jobs = [j for j in valid_shortlisted if (j.get("created_at") or "") >= cutoff_48h]
    remote_jobs = [j for j in valid_shortlisted if j["is_remote_verified"]]
    tier1_jobs = [j for j in valid_shortlisted if j["tier"] == "Tier 1: Product Company / AI Startup"]
    tier2_jobs = [j for j in valid_shortlisted if j["tier"] == "Tier 2: Global Enterprise / IT Services"]
    older_jobs = [j for j in valid_shortlisted if (j.get("created_at") or "") < cutoff_7d]

    return {
        "stats": {
            "total_shortlisted": len(valid_shortlisted),
            "fresh_48h": len(fresh_jobs),
            "remote_count": len(remote_jobs),
            "tier1_count": len(tier1_jobs),
            "tier2_count": len(tier2_jobs),
            "total_applied": total_applied,
            "total_rejected": total_rejected,
            "pending_matching": total_scraped,
            "older_count": len(older_jobs),
        },
        "fresh_jobs": fresh_jobs[:40],
        "remote_jobs": remote_jobs[:50],
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
    <style>
        .gradient-card { background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); }
        .tab-btn.active { border-bottom: 2px solid #38bdf8; color: #38bdf8; font-weight: 600; }
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: #0f172a; }
        ::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
        dialog::backdrop {
            background: rgba(2, 6, 23, 0.82);
            backdrop-filter: blur(6px);
        }
    </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen font-sans antialiased">
    <!-- Header -->
    <header class="border-b border-slate-800 bg-slate-900/80 backdrop-blur sticky top-0 z-40">
        <div class="max-w-7xl mx-auto px-4 py-3 sm:px-6 flex items-center justify-between">
            <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-sky-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-sky-500/20">
                    <i class="fa-solid fa-briefcase text-white text-lg"></i>
                </div>
                <div>
                    <h1 class="text-lg font-bold tracking-tight text-white flex items-center gap-2">
                        Job Hunter Operations
                        <span class="text-xs font-semibold px-2 py-0.5 rounded-full bg-sky-500/10 text-sky-400 border border-sky-500/20">Live</span>
                    </h1>
                    <p class="text-xs text-slate-400">Autonomous Screening, ATS PDF Tailoring & Application Hub</p>
                </div>
            </div>
            <div class="flex items-center gap-2">
                <button onclick="openCustomJobModal()" class="px-3 py-1.5 text-xs font-bold bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-400 hover:to-teal-500 text-white rounded-lg shadow-sm flex items-center gap-1.5 transition">
                    <i class="fa-solid fa-plus"></i> Add Custom Link
                </button>
                <button onclick="archiveStaleJobs()" class="px-3 py-1.5 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg border border-slate-700 flex items-center gap-1.5 transition">
                    <i class="fa-solid fa-broom text-amber-400"></i> Clear Stale (>7d)
                </button>
                <button onclick="fetchJobs()" class="px-3 py-1.5 text-xs font-medium bg-sky-600 hover:bg-sky-500 text-white rounded-lg shadow-sm shadow-sky-600/30 flex items-center gap-1.5 transition">
                    <i class="fa-solid fa-rotate"></i> Refresh
                </button>
            </div>
        </div>
    </header>

    <!-- Main Container -->
    <main class="max-w-7xl mx-auto px-4 py-6 sm:px-6 space-y-6">
        <!-- Metrics Ribbon -->
        <div class="grid grid-cols-2 sm:grid-cols-5 gap-3" id="stats-ribbon">
            <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 flex items-center gap-4">
                <div class="w-12 h-12 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400 text-xl">
                    <i class="fa-solid fa-fire-flame-curved"></i>
                </div>
                <div>
                    <div class="text-2xl font-bold text-white" id="stat-fresh">0</div>
                    <div class="text-xs font-medium text-slate-400">Fresh (Past 48h)</div>
                </div>
            </div>
            <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 flex items-center gap-4">
                <div class="w-12 h-12 rounded-lg bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center text-cyan-400 text-xl">
                    <i class="fa-solid fa-globe"></i>
                </div>
                <div>
                    <div class="text-2xl font-bold text-white" id="stat-remote">0</div>
                    <div class="text-xs font-medium text-slate-400">Remote Roles</div>
                </div>
            </div>
            <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 flex items-center gap-4">
                <div class="w-12 h-12 rounded-lg bg-sky-500/10 border border-sky-500/20 flex items-center justify-center text-sky-400 text-xl">
                    <i class="fa-solid fa-star"></i>
                </div>
                <div>
                    <div class="text-2xl font-bold text-white" id="stat-tier1">0</div>
                    <div class="text-xs font-medium text-slate-400">Tier 1 Startups</div>
                </div>
            </div>
            <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 flex items-center gap-4">
                <div class="w-12 h-12 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 text-xl">
                    <i class="fa-solid fa-circle-check"></i>
                </div>
                <div>
                    <div class="text-2xl font-bold text-white" id="stat-applied">0</div>
                    <div class="text-xs font-medium text-slate-400">Applied Roles</div>
                </div>
            </div>
            <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 flex items-center gap-4">
                <div class="w-12 h-12 rounded-lg bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400 text-xl">
                    <i class="fa-solid fa-layer-group"></i>
                </div>
                <div>
                    <div class="text-2xl font-bold text-white" id="stat-total">0</div>
                    <div class="text-xs font-medium text-slate-400">Total Shortlisted</div>
                </div>
            </div>
        </div>

        <!-- Navigation Tabs -->
        <div class="flex items-center gap-6 border-b border-slate-800 text-sm overflow-x-auto pb-px">
            <button onclick="switchTab('fresh')" class="tab-btn active pb-3 px-1 text-slate-400 hover:text-slate-200 transition flex items-center gap-2" id="tab-btn-fresh">
                <i class="fa-solid fa-bolt text-amber-400"></i> Fresh Drops (48h) <span class="text-xs px-1.5 py-0.5 rounded-full bg-slate-800 text-slate-300" id="badge-fresh">0</span>
            </button>
            <button onclick="switchTab('remote')" class="tab-btn pb-3 px-1 text-slate-400 hover:text-slate-200 transition flex items-center gap-2" id="tab-btn-remote">
                <i class="fa-solid fa-globe text-cyan-400"></i> Remote <span class="text-xs px-1.5 py-0.5 rounded-full bg-slate-800 text-slate-300" id="badge-remote">0</span>
            </button>
            <button onclick="switchTab('tier1')" class="tab-btn pb-3 px-1 text-slate-400 hover:text-slate-200 transition flex items-center gap-2" id="tab-btn-tier1">
                <i class="fa-solid fa-rocket text-sky-400"></i> Tier 1 Product Startups <span class="text-xs px-1.5 py-0.5 rounded-full bg-slate-800 text-slate-300" id="badge-tier1">0</span>
            </button>
            <button onclick="switchTab('tier2')" class="tab-btn pb-3 px-1 text-slate-400 hover:text-slate-200 transition flex items-center gap-2" id="tab-btn-tier2">
                <i class="fa-solid fa-building text-slate-400"></i> Enterprise & Global <span class="text-xs px-1.5 py-0.5 rounded-full bg-slate-800 text-slate-300" id="badge-tier2">0</span>
            </button>
            <button onclick="switchTab('all')" class="tab-btn pb-3 px-1 text-slate-400 hover:text-slate-200 transition flex items-center gap-2" id="tab-btn-all">
                <i class="fa-solid fa-list-check"></i> All Shortlisted <span class="text-xs px-1.5 py-0.5 rounded-full bg-slate-800 text-slate-300" id="badge-all">0</span>
            </button>
            <button onclick="switchTab('applied')" class="tab-btn pb-3 px-1 text-slate-400 hover:text-slate-200 transition flex items-center gap-2" id="tab-btn-applied">
                <i class="fa-solid fa-circle-check text-emerald-400"></i> Applied Tracker <span class="text-xs px-1.5 py-0.5 rounded-full bg-slate-800 text-slate-300" id="badge-applied">0</span>
            </button>
        </div>

        <!-- Search, Filter & Sort Controls -->
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-3.5 flex flex-col sm:flex-row items-center justify-between gap-3 shadow-sm">
            <div class="relative flex-1 w-full">
                <i class="fa-solid fa-magnifying-glass absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-500 text-xs"></i>
                <input type="text" id="search-input" oninput="handleSearch()" placeholder="Search title, company, skills (e.g. PyTorch, React, Python), location..." class="w-full pl-9 pr-8 py-2 text-xs bg-slate-950 border border-slate-800 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-sky-500 transition">
                <button id="search-clear-btn" onclick="clearSearch()" class="hidden absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 text-xs p-1" title="Clear search">
                    <i class="fa-solid fa-xmark"></i>
                </button>
            </div>
            <div class="flex items-center justify-between sm:justify-end w-full sm:w-auto gap-3 shrink-0">
                <div class="flex items-center gap-2">
                    <label for="sort-select" class="text-xs text-slate-400 font-medium whitespace-nowrap"><i class="fa-solid fa-arrow-down-short-wide text-slate-500"></i> Sort:</label>
                    <select id="sort-select" onchange="handleSort()" class="px-2.5 py-2 text-xs bg-slate-950 border border-slate-800 rounded-lg text-slate-300 focus:outline-none focus:border-sky-500 cursor-pointer">
                        <option value="match_desc">Match % (High → Low)</option>
                        <option value="date_desc">Newest First</option>
                        <option value="company_asc">Company (A → Z)</option>
                        <option value="title_asc">Role Title (A → Z)</option>
                    </select>
                </div>
                <div class="text-xs font-semibold px-2.5 py-1.5 rounded-lg bg-slate-800/80 text-slate-300 border border-slate-700/60 whitespace-nowrap" id="search-counter">
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
    <dialog id="job-details-modal" class="bg-slate-900 text-slate-100 border border-slate-700 rounded-2xl p-0 w-full max-w-3xl shadow-2xl m-auto overflow-hidden">
        <div class="flex flex-col max-h-[90vh]">
            <!-- Header -->
            <div class="px-6 py-4 border-b border-slate-800 flex items-start justify-between gap-4 bg-slate-900/90 sticky top-0 z-10">
                <div class="space-y-1.5">
                    <div class="flex items-center gap-2 flex-wrap" id="modal-badges"></div>
                    <h2 class="text-xl font-bold text-white leading-tight" id="modal-title">Job Title</h2>
                    <p class="text-sm text-slate-400 font-medium" id="modal-subtitle">Company • Location</p>
                </div>
                <button onclick="closeDetailsModal()" class="w-8 h-8 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white flex items-center justify-center transition shrink-0" aria-label="Close dialog">
                    <i class="fa-solid fa-xmark"></i>
                </button>
            </div>
            
            <!-- Scrollable Content -->
            <div class="p-6 space-y-5 overflow-y-auto">
                <!-- AI Match Analysis Box -->
                <div id="modal-match-section" class="bg-slate-950/70 border border-slate-800 rounded-xl p-4 space-y-2">
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
                    <div id="modal-description" class="text-xs text-slate-300 whitespace-pre-wrap font-sans bg-slate-950/50 p-4 rounded-xl border border-slate-800/80 leading-relaxed max-h-80 overflow-y-auto select-text"></div>
                </div>
            </div>

            <!-- Footer Actions -->
            <div class="px-6 py-4 border-t border-slate-800 bg-slate-900/90 flex items-center justify-between gap-3 sticky bottom-0">
                <button id="modal-dismiss-btn" class="px-4 py-2 text-xs font-medium text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 rounded-lg transition border border-transparent hover:border-rose-500/20">
                    <i class="fa-solid fa-xmark mr-1"></i> Dismiss
                </button>
                <div class="flex items-center gap-2">
                    <a id="modal-listing-link" href="#" target="_blank" rel="noopener noreferrer" class="px-4 py-2 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg border border-slate-700 flex items-center gap-1.5 transition">
                        <i class="fa-solid fa-arrow-up-right-from-square text-sky-400"></i> View Listing
                    </a>
                    <a id="modal-pdf-link" href="#" target="_blank" class="hidden px-4 py-2 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-sky-400 rounded-lg border border-slate-700 flex items-center gap-1.5 transition">
                        <i class="fa-solid fa-file-pdf"></i> View PDF
                    </a>
                    <button id="modal-reveal-btn" onclick="revealInFinder(currentModalPdfPath)" class="hidden px-3 py-2 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg border border-slate-700 flex items-center gap-1.5 transition" title="Reveal PDF in Finder & copy path">
                        <i class="fa-regular fa-folder-open text-amber-400"></i> Finder
                    </button>
                    <button id="modal-apply-btn" class="px-5 py-2 text-xs font-bold bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-400 hover:to-indigo-500 text-white rounded-lg shadow-md shadow-sky-500/20 flex items-center gap-1.5 transition">
                        <i class="fa-solid fa-bolt"></i> 1-Click Tailor & Apply
                    </button>
                </div>
            </div>
        </div>
    </dialog>

    <!-- Add Custom Job Modal (Native HTML5 Dialog) -->
    <dialog id="custom-job-modal" class="bg-slate-900 text-slate-100 border border-slate-700 rounded-2xl p-0 w-full max-w-lg shadow-2xl m-auto overflow-hidden">
        <form method="dialog" onsubmit="submitCustomJob(event)" class="p-6 space-y-4">
            <div class="flex items-center justify-between border-b border-slate-800 pb-3">
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
                        <input type="url" id="custom-url-input" placeholder="https://jobs.lever.co/..., greenhouse.io, linkedin..." class="flex-1 px-3 py-2 text-xs bg-slate-950 border border-slate-800 rounded-lg focus:outline-none focus:border-sky-500 text-slate-100" />
                        <button type="button" onclick="pasteCustomUrl()" class="px-3 py-2 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg border border-slate-700 transition" title="Paste from clipboard">
                            <i class="fa-solid fa-paste"></i>
                        </button>
                    </div>
                </div>

                <div>
                    <label class="block text-xs font-semibold text-slate-300 mb-1">Raw Job Description (Optional fallback)</label>
                    <textarea id="custom-text-input" rows="4" placeholder="If the role is behind a login or private portal, paste the JD text here..." class="w-full px-3 py-2 text-xs bg-slate-950 border border-slate-800 rounded-lg focus:outline-none focus:border-sky-500 text-slate-100 resize-none font-mono text-[11px]"></textarea>
                </div>
            </div>

            <div id="custom-job-progress" class="hidden p-3 rounded-lg bg-sky-500/10 border border-sky-500/20 text-xs text-sky-300 flex items-center gap-2">
                <i class="fa-solid fa-circle-notch fa-spin text-sky-400"></i>
                <span id="custom-job-status-text">Ingesting listing and screening with AI...</span>
            </div>

            <div class="flex items-center justify-end gap-2 pt-2 border-t border-slate-800">
                <button type="button" onclick="closeCustomJobModal()" class="px-4 py-2 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg border border-slate-700 transition">
                    Cancel
                </button>
                <button type="submit" id="custom-submit-btn" class="px-4 py-2 text-xs font-bold bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-400 hover:to-teal-500 text-white rounded-lg shadow-sm flex items-center gap-1.5 transition">
                    <i class="fa-solid fa-wand-magic-sparkles"></i> Analyze & Ingest
                </button>
            </div>
        </form>
    </dialog>

    <!-- Notification Toast with Undo -->
    <div id="toast" class="fixed bottom-6 right-6 px-4 py-3 rounded-xl bg-slate-900 border border-slate-700 text-sm shadow-2xl transition-all duration-300 transform translate-y-24 opacity-0 z-50 flex items-center gap-3 max-w-md">
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
            document.getElementById('stat-fresh').innerText = s.fresh_48h;
            document.getElementById('stat-remote').innerText = s.remote_count || 0;
            document.getElementById('stat-tier1').innerText = s.tier1_count;
            document.getElementById('stat-applied').innerText = s.total_applied;
            document.getElementById('stat-total').innerText = s.total_shortlisted;

            document.getElementById('badge-fresh').innerText = s.fresh_48h;
            document.getElementById('badge-remote').innerText = s.remote_count || 0;
            document.getElementById('badge-tier1').innerText = s.tier1_count;
            document.getElementById('badge-tier2').innerText = s.tier2_count;
            document.getElementById('badge-all').innerText = s.total_shortlisted;
            document.getElementById('badge-applied').innerText = s.total_applied;
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
            if (currentTab === 'fresh') list = rawData.fresh_jobs;
            else if (currentTab === 'remote') list = rawData.remote_jobs;
            else if (currentTab === 'tier1') list = rawData.tier1_jobs;
            else if (currentTab === 'tier2') list = rawData.tier2_jobs;
            else if (currentTab === 'all') list = rawData.all_shortlisted;
            else if (currentTab === 'applied') list = rawData.applied_jobs;

            const filtered = getFilteredAndSortedJobs(list);
            updateResultCounter(filtered.length, (list || []).length);

            if (!filtered || filtered.length === 0) {
                container.innerHTML = `
                    <div class="col-span-1 md:col-span-2 py-16 text-center text-slate-500">
                        <i class="fa-regular fa-folder-open text-4xl mb-3 block text-slate-600"></i>
                        <p class="text-sm font-medium">No postings match your current filter.</p>
                        ${searchTerm ? `<button onclick="clearSearch()" class="mt-2 text-xs text-sky-400 hover:underline">Clear search filter</button>` : ''}
                    </div>
                `;
                return;
            }

            filtered.forEach(j => {
                const scoreColor = (j.score >= 90) ? 'text-amber-400 bg-amber-400/10 border-amber-400/20' : 'text-sky-400 bg-sky-400/10 border-sky-400/20';
                const tierBadge = j.tier ? `<span class="text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-medium">${j.tier.split(':')[0]}</span>` : '';
                const isRemote = j.is_remote_verified;
                const remoteBadge = isRemote ? `<span class="text-[10px] px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 font-medium flex items-center gap-1"><i class="fa-solid fa-globe text-[9px]"></i> Remote</span>` : '';
                const platformBadge = j.platform ? `<span class="text-[10px] px-2 py-0.5 rounded bg-sky-500/10 text-sky-400 border border-sky-500/20 font-medium">${j.platform}</span>` : '';
                const datePosted = j.date_posted && j.date_posted !== 'nan' ? j.date_posted : 'Recent';
                const hasPdf = j.tailored_resume_pdf_path ? true : false;
                const listingUrl = (j.job_url_direct || j.job_url || '').trim();
                const portalUrl = (j.status_portal_url || '').trim();

                const card = document.createElement('div');
                card.className = "bg-slate-900 border border-slate-800 rounded-xl p-5 hover:border-slate-700 transition flex flex-col justify-between space-y-4 shadow-sm";
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
                                <span class="px-2 py-1 text-xs font-bold rounded-lg border text-emerald-400 bg-emerald-500/10 border-emerald-500/20 shrink-0">Applied</span>
                            </div>
                        </div>
                        <div class="flex items-center justify-between pt-3 border-t border-slate-800/80 gap-2 flex-wrap">
                            <button onclick="openDetailsModal('${j.job_id}')" class="px-3 py-1.5 text-xs font-medium text-slate-300 hover:text-white bg-slate-800/90 hover:bg-slate-700 rounded-lg border border-slate-700 flex items-center gap-1.5 transition shadow-sm" title="View Job Description & Tailoring Notes">
                                <i class="fa-solid fa-eye text-[10px] text-indigo-400"></i> Details
                            </button>
                            <div class="flex items-center gap-2">
                                ${portalUrl ? `<a href="${portalUrl}" target="_blank" rel="noopener noreferrer" class="px-3 py-1.5 text-xs font-bold bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white rounded-lg shadow-sm flex items-center gap-1.5 transition" title="Open candidate application status tracking portal"><i class="fa-solid fa-id-card"></i> Check Status (${j.platform || 'Portal'})</a>` : ''}
                                ${listingUrl ? `<a href="${listingUrl}" target="_blank" rel="noopener noreferrer" class="px-3 py-1.5 text-xs font-medium bg-slate-800/80 hover:bg-slate-700 text-slate-300 hover:text-white rounded-lg border border-slate-700 flex items-center gap-1.5 transition"><i class="fa-solid fa-arrow-up-right-from-square text-[10px] text-sky-400"></i> View Listing</a>` : ''}
                                ${hasPdf ? `
                                <button onclick="revealInFinder('${escapeHtml(j.tailored_resume_pdf_path)}')" class="px-2.5 py-1.5 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white rounded-lg border border-slate-700 flex items-center gap-1 transition" title="Reveal PDF in Finder & copy path"><i class="fa-regular fa-folder-open text-amber-400"></i></button>
                                <a href="/pdf?path=${encodeURIComponent(j.tailored_resume_pdf_path)}" target="_blank" class="px-3 py-1.5 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-sky-400 rounded-lg border border-slate-700 flex items-center gap-1.5 transition"><i class="fa-solid fa-file-pdf"></i> View PDF</a>` : ''}
                            </div>
                        </div>
                    `;
                } else {
                    card.innerHTML = `
                        <div class="space-y-3">
                            <div class="flex items-start justify-between gap-2">
                                <div class="space-y-1">
                                    <div class="flex items-center gap-2 flex-wrap">
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
                            ${j.matching_notes ? `<p class="text-xs text-slate-400 bg-slate-950/60 p-2.5 rounded-lg border border-slate-800/60 leading-relaxed"><i class="fa-solid fa-circle-info text-sky-400 mr-1"></i> ${escapeHtml(j.matching_notes)}</p>` : ''}
                        </div>

                        <div class="flex items-center justify-between pt-3 border-t border-slate-800/80 gap-2 flex-wrap">
                            <div class="flex items-center gap-2">
                                <button onclick="dismissJob('${j.job_id}')" class="px-3 py-1.5 text-xs font-medium text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 rounded-lg transition border border-transparent hover:border-rose-500/20" title="Dismiss from shortlist">
                                    <i class="fa-solid fa-xmark"></i> Dismiss
                                </button>
                                <button onclick="openDetailsModal('${j.job_id}')" class="px-3 py-1.5 text-xs font-medium text-slate-300 hover:text-white bg-slate-800/90 hover:bg-slate-700 rounded-lg border border-slate-700 flex items-center gap-1.5 transition shadow-sm" title="View Full Description & Match Details">
                                    <i class="fa-solid fa-eye text-[10px] text-indigo-400"></i> Details
                                </button>
                                ${listingUrl ? `
                                <a href="${listingUrl}" target="_blank" rel="noopener noreferrer" class="px-3 py-1.5 text-xs font-medium text-slate-300 hover:text-white bg-slate-800/90 hover:bg-slate-700 rounded-lg border border-slate-700 flex items-center gap-1.5 transition shadow-sm" title="View original job listing in a new tab">
                                    <i class="fa-solid fa-arrow-up-right-from-square text-[10px] text-sky-400"></i> View Listing
                                </a>` : ''}
                            </div>
                            <div class="flex items-center gap-2">
                                ${hasPdf ? `
                                <button onclick="revealInFinder('${escapeHtml(j.tailored_resume_pdf_path)}')" class="px-2.5 py-1.5 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white rounded-lg border border-slate-700 flex items-center gap-1 transition" title="Reveal PDF in Finder & copy path"><i class="fa-regular fa-folder-open text-amber-400"></i></button>
                                <a href="/pdf?path=${encodeURIComponent(j.tailored_resume_pdf_path)}" target="_blank" class="px-3 py-1.5 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-sky-400 rounded-lg border border-slate-700 flex items-center gap-1.5 transition" title="Open Tailored Resume PDF"><i class="fa-solid fa-file-pdf"></i> PDF</a>` : ''}
                                <button onclick="applyJob('${j.job_id}', this)" class="px-4 py-1.5 text-xs font-bold bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-400 hover:to-indigo-500 text-white rounded-lg shadow-md shadow-sky-500/20 flex items-center gap-1.5 transition">
                                    <i class="fa-solid fa-bolt"></i> 1-Click Tailor & Apply
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
            const allLists = [rawData.fresh_jobs, rawData.remote_jobs, rawData.tier1_jobs, rawData.tier2_jobs, rawData.all_shortlisted, rawData.applied_jobs];
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
            if (job.tier) {
                badgesEl.innerHTML += `<span class="text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-medium">${job.tier.split(':')[0]}</span>`;
            }
            if (job.is_remote_verified) {
                badgesEl.innerHTML += `<span class="text-[10px] px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 font-medium flex items-center gap-1"><i class="fa-solid fa-globe text-[9px]"></i> Remote</span>`;
            }
            if (job.platform) {
                badgesEl.innerHTML += `<span class="text-[10px] px-2 py-0.5 rounded bg-sky-500/10 text-sky-400 border border-sky-500/20 font-medium">${job.platform}</span>`;
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
                ? 'px-2.5 py-0.5 rounded text-xs font-extrabold border text-amber-400 bg-amber-400/10 border-amber-400/20'
                : 'px-2.5 py-0.5 rounded text-xs font-extrabold border text-sky-400 bg-sky-400/10 border-sky-400/20';

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
                        chip.className = "text-[11px] px-2.5 py-1 rounded-md bg-slate-800 text-slate-200 border border-slate-700/80 font-mono";
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

            if (!url && !text) {
                showToast('Please enter a job URL or raw job description.', true);
                return;
            }

            const progress = document.getElementById('custom-job-progress');
            const statusText = document.getElementById('custom-job-status-text');
            const submitBtn = document.getElementById('custom-submit-btn');

            progress.classList.remove('hidden');
            submitBtn.disabled = true;
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
                        window.location.href = '/apply?id=' + encodeURIComponent(data.job_id);
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

        async function applyJob(jobId, btn) {
            const originalText = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i> Tailoring Resume...`;

            try {
                const res = await fetch('/api/apply', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ job_id: jobId })
                });
                const data = await res.json();
                if (data.success) {
                    if (data.resume_pdf_path) {
                        try {
                            await navigator.clipboard.writeText(data.resume_pdf_path);
                        } catch (_) {}
                        window.open('/pdf?path=' + encodeURIComponent(data.resume_pdf_path), '_blank');
                    }
                    showToast('Tailored PDF opened! File revealed in Finder & path copied to clipboard');
                    const card = document.getElementById('job-' + jobId);
                    if (card) {
                        card.style.opacity = '0.4';
                        setTimeout(() => fetchJobs(), 1500);
                    }
                    closeDetailsModal();
                } else {
                    showToast('Error: ' + (data.error || 'Failed to apply'), true);
                    btn.disabled = false;
                    btn.innerHTML = originalText;
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
                const allLists = [rawData.fresh_jobs, rawData.remote_jobs, rawData.tier1_jobs, rawData.tier2_jobs, rawData.all_shortlisted];
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
                        const allLists = [rawData.fresh_jobs, rawData.remote_jobs, rawData.tier1_jobs, rawData.tier2_jobs, rawData.all_shortlisted];
                        for (const list of allLists) {
                            if (list) {
                                const idx = list.findIndex(x => x.job_id === jobId);
                                if (idx !== -1) list.splice(idx, 1);
                            }
                        }
                        if (rawData.stats) {
                            rawData.stats.total_shortlisted = Math.max(0, rawData.stats.total_shortlisted - 1);
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
            self.send_header("Location", f"/apply?id={job_id}")
            self.end_headers()
            return

        elif path == "/apply":
            query = urllib.parse.parse_qs(parsed.query)
            job_id = query.get("id", [""])[0]
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

            # Execute Tailor pipeline
            materials = tailor.tailor_materials(job_id)
            if not materials:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"<h1>Error: Failed to generate tailored resume.</h1>")
                return

            resume_path, resume_pdf_path = materials[0], materials[1]
            target_url = job["job_url_direct"] or job["job_url"]

            # Open target URL in default browser
            if target_url:
                webbrowser.open(target_url)

            # Reveal tailored PDF in Finder on macOS for immediate drag-and-drop
            if resume_pdf_path and os.path.exists(resume_pdf_path) and sys.platform == "darwin":
                try:
                    subprocess.run(["open", "-R", resume_pdf_path], check=False)
                except Exception:
                    pass

            # Mark as applied in DB
            db.mark_as_applied(job_id, resume_path, None, resume_pdf_path, None)

            success_html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Application Triggered — {job['company']}</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-950 text-slate-100 flex items-center justify-center min-h-screen p-6">
    <div class="max-w-lg w-full bg-slate-900 border border-slate-800 rounded-2xl p-8 text-center space-y-6 shadow-2xl">
        <div class="w-16 h-16 bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded-full flex items-center justify-center mx-auto text-3xl">
            ✓
        </div>
        <div>
            <h1 class="text-2xl font-bold text-white">Apply Script Executed!</h1>
            <p class="text-slate-400 text-sm mt-1">Application materials generated for <b>{job['title']}</b> at <b>{job['company']}</b></p>
        </div>
        <div class="bg-slate-950 p-4 rounded-xl text-left text-xs space-y-2 border border-slate-800 text-slate-300">
            <div><b>Target URL Opened:</b> <a href="{target_url}" target="_blank" class="text-sky-400 underline truncate block">{target_url}</a></div>
            <div><b>Status:</b> <span class="text-emerald-400 font-semibold">Marked as Applied in Database</span></div>
        </div>
        <div class="flex items-center justify-center gap-3">
            <a href="/pdf?path={urllib.parse.quote(resume_pdf_path)}" target="_blank" class="px-5 py-2.5 bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-400 hover:to-indigo-500 text-white font-medium rounded-xl text-sm transition shadow-lg shadow-sky-500/20">
                📄 Open Tailored Resume PDF
            </a>
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
            self.wfile.write(success_html.encode("utf-8"))
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
            if pdf_path and os.path.exists(pdf_path) and pdf_path.endswith(".pdf"):
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Disposition", f'inline; filename="{os.path.basename(pdf_path)}"')
                self.end_headers()
                with open(pdf_path, "rb") as f:
                    self.wfile.write(f.read())
                return
            else:
                self.send_response(404)
                self.end_headers()
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
            if not job_id:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Missing job_id"}).encode("utf-8"))
                return

            try:
                # 1. Fetch job details
                conn = db.get_db_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
                job = cursor.fetchone()
                conn.close()

                if not job:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Job not found"}).encode("utf-8"))
                    return

                # 2. Tailor materials
                materials = tailor.tailor_materials(job_id)
                if not materials:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Failed to tailor materials"}).encode("utf-8"))
                    return

                resume_path, resume_pdf_path = materials[0], materials[1]
                target_url = job["job_url_direct"] or job["job_url"]

                # 3. Open browser directly to target URL
                if target_url:
                    webbrowser.open(target_url)

                # 4. Reveal tailored PDF in Finder on macOS for immediate drag-and-drop
                if resume_pdf_path and os.path.exists(resume_pdf_path) and sys.platform == "darwin":
                    try:
                        subprocess.run(["open", "-R", resume_pdf_path], check=False)
                    except Exception:
                        pass

                # 5. Mark as applied in database
                db.mark_as_applied(job_id, resume_path, None, resume_pdf_path, None)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": True,
                    "job_id": job_id,
                    "resume_pdf_path": resume_pdf_path,
                    "url": target_url
                }).encode("utf-8"))
                return

            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
                return

        elif path == "/api/reveal":
            pdf_path = params.get("path")
            if pdf_path and os.path.exists(pdf_path):
                if sys.platform == "darwin":
                    try:
                        subprocess.run(["open", "-R", pdf_path], check=False)
                    except Exception:
                        pass
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
                return
            else:
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "File not found"}).encode("utf-8"))
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

        self.send_response(404)
        self.end_headers()


def start_server(open_browser: bool = True):
    """Start local web dashboard server."""
    server_address = ("127.0.0.1", PORT)
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(server_address, DashboardRequestHandler)
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
