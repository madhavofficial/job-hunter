"""Dashboard Generator for Job Hunter.

Generates a clean, date-aware Markdown and PDF dashboard prioritizing:
1. 🔥 Fresh Today (Discovered in Today's run / Past 24h)
2. 📅 Yesterday's Matches (Past 24-48h)
3. 📁 Active Backlog (Past 3-5 Days)

Automatically auto-archives unapplied listings older than 5 days so the active table
stays ultra-clean and relevant.
"""

import os
from datetime import datetime, timedelta

import db
from screening import classify_company_tier


def auto_archive_stale_jobs(days: int = 5):
    """Move unapplied shortlisted jobs older than `days` to rejected to keep shortlist fresh."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    conn = db.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE jobs
    SET status = 'rejected'
    WHERE status = 'shortlisted' AND (created_at < ? OR created_at IS NULL)
    """, (cutoff,))
    archived_count = cursor.rowcount
    conn.commit()
    conn.close()
    return archived_count


def generate_dashboard():
    db.init_db()

    # 1. Auto-archive older backlog
    archived_stale = auto_archive_stale_jobs(days=5)

    # 2. Retrieve active shortlisted jobs
    all_shortlisted = db.get_shortlisted_jobs()
    shortlisted = [j for j in all_shortlisted if not classify_company_tier(j["company"]).startswith("Tier 3")]
    applied = db.get_applied_jobs()

    # Database stats
    conn = db.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM jobs WHERE status = 'rejected'")
    total_rejected = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM jobs WHERE status = 'scraped'")
    total_scraped = cursor.fetchone()[0]
    conn.close()

    # Date buckets
    today_str = datetime.now().strftime("%Y-%m-%d")
    yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    freshness_cutoff = (datetime.now() - timedelta(hours=48)).strftime("%Y-%m-%d %H:%M:%S")

    today_jobs = [j for j in shortlisted if (j.get("created_at") or "").startswith(today_str)]
    yesterday_jobs = [j for j in shortlisted if (j.get("created_at") or "").startswith(yesterday_str)]
    earlier_jobs = [j for j in shortlisted if j not in today_jobs and j not in yesterday_jobs]
    fresh_48h = [j for j in shortlisted if (j.get("created_at") or "") >= freshness_cutoff]

    now_str = datetime.now().strftime("%d %b %Y, %I:%M %p")

    md_content = f"""# Job Hunter Dashboard — {now_str}

## 📊 Summary Statistics
- **🔥 Fresh (Past 48h)**: {len(fresh_48h)} new opportunities
- **📅 Yesterday ({yesterday_str})**: {len(yesterday_jobs)} active opportunities
- **📁 Earlier This Week**: {len(earlier_jobs)} active opportunities
- **✅ Applied Roles**: {len(applied)}
- **🧹 Auto-Archived (>5d Old)**: {archived_stale}

---

"""

    def render_job_table(job_list, section_title, section_desc, icon="🔥"):
        if not job_list:
            return f"## {icon} {section_title}\n*{section_desc}*\n\n*No opportunities in this bucket.*\n\n---\n\n"

        tier1 = [j for j in job_list if classify_company_tier(j["company"]) == "Tier 1: Product Company / AI Startup"]
        tier2 = [j for j in job_list if classify_company_tier(j["company"]) == "Tier 2: Global Enterprise / IT Services"]
        other = [j for j in job_list if j not in tier1 and j not in tier2]

        out = f"## {icon} {section_title} ({len(job_list)} Positions)\n*{section_desc}*\n\n"

        if tier1:
            out += "### 🌟 Tier 1: Product Companies & Verified AI Startups\n\n"
            out += "| Score | Job ID | Company | Job Title | Location | Direct ATS Link | ⚡ Auto-Apply | ✕ Dismiss |\n"
            out += "| :---: | :--- | :--- | :--- | :--- | :---: | :---: | :---: |\n"
            for j in tier1:
                url = j["job_url_direct"] or j["job_url"] or "#"
                url_text = "[Apply Direct ↗]" if j["job_url_direct"] else "[View Listing ↗]"
                apply_link = f"http://127.0.0.1:8765/apply?id={j['job_id']}"
                dismiss_link = f"http://127.0.0.1:8765/dismiss?id={j['job_id']}"
                out += f"| **{j['score']}%** | `{j['job_id']}` | **{j['company']}** | {j['title']} | {j['location'] or 'India / Remote'} | [{url_text}]({url}) | [[⚡ Apply ↗]]({apply_link}) | [[✕ Do Not Consider]]({dismiss_link}) |\n"
            out += "\n"

        if tier2:
            out += "### 🏢 Tier 2: Global Enterprises & IT Services\n\n"
            out += "| Score | Job ID | Company | Job Title | Location | Direct ATS Link | ⚡ Auto-Apply | ✕ Dismiss |\n"
            out += "| :---: | :--- | :--- | :--- | :--- | :---: | :---: | :---: |\n"
            for j in tier2:
                url = j["job_url_direct"] or j["job_url"] or "#"
                url_text = "[Apply Direct ↗]" if j["job_url_direct"] else "[View Listing ↗]"
                apply_link = f"http://127.0.0.1:8765/apply?id={j['job_id']}"
                dismiss_link = f"http://127.0.0.1:8765/dismiss?id={j['job_id']}"
                out += f"| **{j['score']}%** | `{j['job_id']}` | **{j['company']}** | {j['title']} | {j['location'] or 'India / Remote'} | [{url_text}]({url}) | [[⚡ Apply ↗]]({apply_link}) | [[✕ Do Not Consider]]({dismiss_link}) |\n"
            out += "\n"

        if other:
            out += "<details><summary><b>Other Matched Roles (Click to expand)</b></summary>\n\n"
            out += "| Score | Job ID | Company | Job Title | Location | Direct ATS Link | ⚡ Auto-Apply | ✕ Dismiss |\n"
            out += "| :---: | :--- | :--- | :--- | :--- | :---: | :---: | :---: |\n"
            for j in other:
                url = j["job_url_direct"] or j["job_url"] or "#"
                url_text = "[Apply Direct ↗]" if j["job_url_direct"] else "[View Listing ↗]"
                apply_link = f"http://127.0.0.1:8765/apply?id={j['job_id']}"
                dismiss_link = f"http://127.0.0.1:8765/dismiss?id={j['job_id']}"
                out += f"| {j['score']}% | `{j['job_id']}` | {j['company']} | {j['title']} | {j['location'] or 'India / Remote'} | [{url_text}]({url}) | [[⚡ Apply ↗]]({apply_link}) | [[✕ Do Not Consider]]({dismiss_link}) |\n"
            out += "\n</details>\n\n"

        out += "---\n\n"
        return out

    # Render Sections
    md_content += render_job_table(today_jobs, f"Fresh Today — {today_str}", "Discovered during today's scraping and AI evaluation run.", "🔥")
    md_content += render_job_table(yesterday_jobs, f"Yesterday's Opportunities — {yesterday_str}", "High-fit roles discovered in the previous 24-48 hours.", "📅")
    if earlier_jobs:
        md_content += render_job_table(earlier_jobs, "Earlier This Week (Active Backlog)", "Roles from 2-4 days ago still open for applications.", "📁")

    # Render Evidence Highlights for Today's Top Matches
    if today_jobs:
        md_content += "## 📝 Today's Top Matches — Technical Evidence\n\n"
        for j in today_jobs[:15]:
            url = j["job_url_direct"] or j["job_url"] or "#"
            apply_link = f"http://127.0.0.1:8765/apply?id={j['job_id']}"
            dismiss_link = f"http://127.0.0.1:8765/dismiss?id={j['job_id']}"
            md_content += f"#### 💻 {j['title']} — **{j['company']}** ({j['location'] or 'India / Remote'})\n"
            md_content += f"- **Job ID**: `{j['job_id']}` | **Match Score**: **{j['score']}%**\n"
            md_content += f"- **Links**: [Portal Listing ↗]({url}) | [[⚡ 1-Click Apply ↗]]({apply_link}) | [[✕ Dismiss]]({dismiss_link})\n"
            if j.get("matching_notes"):
                md_content += f"- **Analysis**: {j['matching_notes']}\n"
            if j.get("evidence"):
                md_content += f"- **Evidence**: {j['evidence']}\n"
            md_content += "\n---\n\n"

    # Save Markdown Dashboard
    base_dir = os.path.dirname(os.path.abspath(__file__))
    latest_md_path = os.path.join(base_dir, "dashboard.md")
    with open(latest_md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    # Save Dated Archive
    dashboards_dir = os.path.join(base_dir, "dashboards")
    os.makedirs(dashboards_dir, exist_ok=True)
    dated_md_path = os.path.join(dashboards_dir, f"dashboard-{today_str}.md")
    with open(dated_md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    # Compile PDF Dashboard
    try:
        from pdf_utils import markdown_to_pdf
        pdf_path = os.path.join(base_dir, "dashboard.pdf")
        markdown_to_pdf(md_content, pdf_path)
    except Exception as e:
        print(f"Warning: PDF generation failed: {e}", file=sys.stderr)

    print(f"Latest Dashboard saved at: {latest_md_path}")
    print(f"Dated Archive saved at: {dated_md_path}")
    print(f"Daily report: Found {len(today_jobs)} fresh opportunities today ({today_str}).")
    print(f"Open dashboard: file://{latest_md_path}")



if __name__ == "__main__":
    generate_dashboard()
