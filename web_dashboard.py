"""Interactive Web Dashboard & 1-Click Application Server for Job Hunter.

Provides a clean, local web interface where you can:
- View categorized job matches (Fresh Today, Tier 1 AI Startups, Tier 2 Enterprises)
- Click [⚡ 1-Click Apply & Tailor] to generate an ATS Single-Page Resume PDF, open the application URL in your browser, and mark it applied.
- Click [✕ Dismiss] to instantly remove jobs from your shortlist feed.
- Click [🧹 Clean Stale Jobs] to auto-archive older unapplied listings.
"""

import http.server
import json
import os
import re
import socketserver
import sys
import threading
import urllib.parse
import webbrowser
from datetime import datetime, timedelta

import db
import tailor
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
           matching_notes, tailored_resume_pdf_path, created_at, status
    FROM jobs
    WHERE status = 'shortlisted'
    ORDER BY score DESC, created_at DESC
    """)
    all_shortlisted = [dict(r) for r in cursor.fetchall()]

    # Query the recent applied jobs shown in the tracker.
    cursor.execute("""
    SELECT job_id, site, job_url, job_url_direct, title, company, location, date_posted, score,
           tailored_resume_pdf_path, created_at, status
    FROM jobs
    WHERE status = 'applied'
    ORDER BY created_at DESC LIMIT 25
    """)
    applied = [dict(r) for r in cursor.fetchall()]
    cursor.execute("SELECT COUNT(*) FROM jobs WHERE status = 'applied'")
    total_applied = len(applied)

    # Total counts
    cursor.execute("SELECT COUNT(*) FROM jobs WHERE status = 'rejected'")
    total_rejected = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM jobs WHERE status = 'scraped'")
    total_scraped = cursor.fetchone()[0]
    conn.close()

    # Filter out unverified agencies
    valid_shortlisted = []
    for j in all_shortlisted:
        tier = classify_company_tier(j["company"])
        if not tier.startswith("Tier 3"):
            j["tier"] = tier
            j["apply_url"] = j["job_url_direct"] or j["job_url"]
            j["is_remote_verified"] = is_job_truly_remote(j)
            valid_shortlisted.append(j)

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
        "fresh_jobs": fresh_jobs[:30],
        "remote_jobs": remote_jobs[:40],
        "tier1_jobs": tier1_jobs[:35],
        "tier2_jobs": tier2_jobs[:25],
        "all_shortlisted": valid_shortlisted[:50],
        "applied_jobs": applied,
    }


HTML_TEMPLATE = """<!DOCTYPE html>
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
    </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen font-sans antialiased">
    <!-- Header -->
    <header class="border-b border-slate-800 bg-slate-900/80 backdrop-blur sticky top-0 z-50">
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
                <button onclick="addCustomJob()" class="px-3 py-1.5 text-xs font-bold bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-400 hover:to-teal-500 text-white rounded-lg shadow-sm flex items-center gap-1.5 transition">
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

        <!-- Job Cards Grid -->
        <div id="jobs-container" class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <!-- Rendered dynamically -->
        </div>
    </main>

    <!-- Notification Toast -->
    <div id="toast" class="fixed bottom-6 right-6 px-4 py-3 rounded-xl bg-slate-900 border border-slate-700 text-sm shadow-2xl transition-all duration-300 transform translate-y-24 opacity-0 z-50 flex items-center gap-3">
        <i id="toast-icon" class="fa-solid fa-circle-check text-emerald-400 text-lg"></i>
        <div id="toast-msg" class="text-slate-200 font-medium">Notification message</div>
    </div>

    <script>
        let currentTab = 'fresh';
        let rawData = null;

        function showToast(msg, isError = false) {
            const toast = document.getElementById('toast');
            const icon = document.getElementById('toast-icon');
            document.getElementById('toast-msg').innerText = msg;

            icon.className = isError ? 'fa-solid fa-triangle-exclamation text-rose-400 text-lg' : 'fa-solid fa-circle-check text-emerald-400 text-lg';
            toast.classList.remove('translate-y-24', 'opacity-0');
            setTimeout(() => {
                toast.classList.add('translate-y-24', 'opacity-0');
            }, 4000);
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
            document.getElementById('tab-btn-' + tab).classList.add('active');
            renderCards();
        }

        function renderCards() {
            const container = document.getElementById('jobs-container');
            container.innerHTML = '';

            let list = [];
            if (currentTab === 'fresh') list = rawData.fresh_jobs;
            else if (currentTab === 'remote') list = rawData.remote_jobs;
            else if (currentTab === 'tier1') list = rawData.tier1_jobs;
            else if (currentTab === 'tier2') list = rawData.tier2_jobs;
            else if (currentTab === 'all') list = rawData.all_shortlisted;
            else if (currentTab === 'applied') list = rawData.applied_jobs;

            if (!list || list.length === 0) {
                container.innerHTML = `
                    <div class="col-span-2 py-16 text-center text-slate-500">
                        <i class="fa-regular fa-folder-open text-4xl mb-3 block"></i>
                        <p class="text-sm">No postings currently in this view.</p>
                    </div>
                `;
                return;
            }

            list.forEach(j => {
                const scoreColor = (j.score >= 90) ? 'text-amber-400 bg-amber-400/10 border-amber-400/20' : 'text-sky-400 bg-sky-400/10 border-sky-400/20';
                const tierBadge = j.tier ? `<span class="text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-medium">${j.tier.split(':')[0]}</span>` : '';
                const isRemote = j.is_remote_verified;
                const remoteBadge = isRemote ? `<span class="text-[10px] px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 font-medium flex items-center gap-1"><i class="fa-solid fa-globe text-[9px]"></i> Remote</span>` : '';
                const datePosted = j.date_posted && j.date_posted !== 'nan' ? j.date_posted : 'Recent';
                const hasPdf = j.tailored_resume_pdf_path ? true : false;
                const listingUrl = (j.job_url_direct || j.job_url || '').trim();

                const card = document.createElement('div');
                card.className = "bg-slate-900 border border-slate-800 rounded-xl p-5 hover:border-slate-700 transition flex flex-col justify-between space-y-4 shadow-sm";
                card.id = `job-${j.job_id}`;

                if (currentTab === 'applied') {
                    card.innerHTML = `
                        <div class="space-y-2">
                            <div class="flex items-start justify-between gap-3">
                                <div>
                                    <h3 class="text-base font-bold text-white leading-snug">
                                        ${listingUrl ? `<a href="${listingUrl}" target="_blank" rel="noopener noreferrer" class="hover:text-sky-400 transition inline-flex items-center gap-1.5">${j.title} <i class="fa-solid fa-arrow-up-right-from-square text-[11px] text-slate-500"></i></a>` : j.title}
                                    </h3>
                                    <p class="text-sm font-medium text-slate-300">${j.company} &bull; <span class="text-xs text-slate-400">${j.location || 'Remote'}</span></p>
                                </div>
                                <span class="px-2 py-1 text-xs font-bold rounded-lg border text-emerald-400 bg-emerald-500/10 border-emerald-500/20">Applied</span>
                            </div>
                        </div>
                        <div class="flex items-center justify-between pt-3 border-t border-slate-800/80 gap-2">
                            <span class="text-xs text-slate-500">Applied: ${j.created_at || 'Recently'}</span>
                            <div class="flex items-center gap-2">
                                ${listingUrl ? `<a href="${listingUrl}" target="_blank" rel="noopener noreferrer" class="px-3 py-1.5 text-xs font-medium bg-slate-800/80 hover:bg-slate-700 text-slate-300 hover:text-white rounded-lg border border-slate-700 flex items-center gap-1.5 transition"><i class="fa-solid fa-arrow-up-right-from-square text-[10px] text-sky-400"></i> View Listing</a>` : ''}
                                ${hasPdf ? `<a href="/pdf?path=${encodeURIComponent(j.tailored_resume_pdf_path)}" target="_blank" class="px-3 py-1.5 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-sky-400 rounded-lg border border-slate-700 flex items-center gap-1.5 transition"><i class="fa-solid fa-file-pdf"></i> View Tailored PDF</a>` : ''}
                            </div>
                        </div>
                    `;
                } else {
                    card.innerHTML = `
                        <div class="space-y-3">
                            <div class="flex items-start justify-between gap-2">
                                <div class="space-y-1">
                                    <div class="flex items-center gap-2">
                                        ${tierBadge}
                                        ${remoteBadge}
                                        <span class="text-[10px] text-slate-400"><i class="fa-regular fa-clock"></i> ${datePosted}</span>
                                    </div>
                                    <h3 class="text-base font-bold text-white leading-snug">
                                        ${listingUrl ? `<a href="${listingUrl}" target="_blank" rel="noopener noreferrer" class="hover:text-sky-400 transition inline-flex items-center gap-1.5">${j.title} <i class="fa-solid fa-arrow-up-right-from-square text-[11px] text-slate-500"></i></a>` : j.title}
                                    </h3>
                                    <p class="text-sm font-medium text-slate-300">${j.company} <span class="text-xs text-slate-400">&bull; ${j.location || 'India'}</span></p>
                                </div>
                                <div class="px-2.5 py-1 text-xs font-extrabold rounded-lg border ${scoreColor} shrink-0">
                                    ${j.score}% Match
                                </div>
                            </div>
                            ${j.matching_notes ? `<p class="text-xs text-slate-400 bg-slate-950/60 p-2.5 rounded-lg border border-slate-800/60 leading-relaxed"><i class="fa-solid fa-circle-info text-sky-400 mr-1"></i> ${j.matching_notes}</p>` : ''}
                        </div>

                        <div class="flex items-center justify-between pt-3 border-t border-slate-800/80 gap-2">
                            <div class="flex items-center gap-2">
                                <button onclick="dismissJob('${j.job_id}')" class="px-3 py-1.5 text-xs font-medium text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 rounded-lg transition border border-transparent hover:border-rose-500/20" title="Dismiss from shortlisted">
                                    <i class="fa-solid fa-xmark"></i> Dismiss
                                </button>
                                ${listingUrl ? `
                                <a href="${listingUrl}" target="_blank" rel="noopener noreferrer" class="px-3 py-1.5 text-xs font-medium text-slate-300 hover:text-white bg-slate-800/90 hover:bg-slate-700 rounded-lg border border-slate-700 flex items-center gap-1.5 transition shadow-sm" title="View original job listing in a new tab">
                                    <i class="fa-solid fa-arrow-up-right-from-square text-[10px] text-sky-400"></i> View Listing
                                </a>` : ''}
                            </div>
                            <div class="flex items-center gap-2">
                                ${hasPdf ? `<a href="/pdf?path=${encodeURIComponent(j.tailored_resume_pdf_path)}" target="_blank" class="px-3 py-1.5 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-sky-400 rounded-lg border border-slate-700 flex items-center gap-1.5 transition" title="Open Tailored Resume PDF"><i class="fa-solid fa-file-pdf"></i> PDF</a>` : ''}
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
                    showToast('Tailored PDF generated & browser opened for ' + jobId);
                    const card = document.getElementById('job-' + jobId);
                    if (card) {
                        card.style.opacity = '0.4';
                        setTimeout(() => fetchJobs(), 1500);
                    }
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
            try {
                const res = await fetch('/api/dismiss', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ job_id: jobId })
                });
                const data = await res.json();
                if (data.success) {
                    const card = document.getElementById('job-' + jobId);
                    if (card) {
                        card.remove();
                        showToast('Job dismissed');
                    }
                }
            } catch (e) {
                showToast('Failed to dismiss: ' + e, true);
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

        async function addCustomJob() {
            const url = prompt("Paste any Job Listing URL (LinkedIn, Greenhouse, Lever, Workday, etc.):");
            if (!url || !url.trim()) return;
            showToast("Scraping & analyzing custom job link with AI... Please wait 5-10s.");
            try {
                const res = await fetch('/api/custom', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: url.trim() })
                });
                const data = await res.json();
                if (data.success && data.job_id) {
                    showToast("Custom job added! Starting tailored ATS resume generation...");
                    window.location.href = '/apply?id=' + encodeURIComponent(data.job_id);
                } else {
                    showToast("Failed to add job: " + (data.error || "Unknown error"), true);
                }
            } catch (e) {
                showToast("Failed to process custom link: " + e, true);
            }
        }

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

                # 4. Mark as applied in database
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

        elif path == "/api/dismiss":
            job_id = params.get("job_id")
            if job_id:
                db.mark_as_rejected(job_id)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
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
