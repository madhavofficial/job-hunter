import os
from datetime import datetime
import db

def generate_dashboard():
    db.init_db()
    
    # Retrieve jobs
    shortlisted = db.get_shortlisted_jobs()
    applied = db.get_applied_jobs()
    
    # Count stats
    total_shortlisted = len(shortlisted)
    total_applied = len(applied)
    
    # Connect to count total rejected
    conn = db.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM jobs WHERE status = 'rejected'")
    total_rejected = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM jobs WHERE status = 'scraped'")
    total_scraped = cursor.fetchone()[0]
    conn.close()
    
    # Sort shortlisted into Strong (>=85) and Possible (75-84)
    strong_matches = [j for j in shortlisted if j['score'] >= 85]
    possible_matches = [j for j in shortlisted if j['score'] < 85]

    # Known enterprise list for heuristic tiering
    known_enterprises = ["novartis", "qualcomm", "munich re", "dhl", "infosys", "ust", "indium", "stripe", "amazon", "google", "microsoft", "oracle", "accenture", "tcs", "wipro", "cognizant", "capgemini", "ibm", "nuvama", "idfc", "morningstar", "solventum", "ixigo"]
    known_agencies = [
        "zepcruit", "hiringhood", "principle pride", "top gen ai jobs", "minute sourcing", 
        "codepillars", "rediente", "talent", "staffing", "consulting", "services", "workforce", 
        "recruit", "rytloop", "genesect", "rythiring", "absolutehub", "tasks expert", "zenithbyte",
        "nexal iit", "sparks to ideas", "sourcing", "uplers", "dasp digital", "zerotwo", "solution",
        "technologies pvt", "it private limited", "tech pvt", "jansoft"
    ]

    def categorize_tier(job):
        comp = (job['company'] or '').strip().lower()
        if not comp or comp in ["none", "confidential", "private limited", "company name"] or any(a in comp for a in known_agencies):
            return "Tier 3: Staffing Agency / Unverified"
        if any(e in comp for e in known_enterprises):
            return "Tier 2: Global Enterprise / IT Services"
        return "Tier 1: Product Company / AI Startup"

    # Separate Strong Matches by Tier
    tier1_strong = [j for j in strong_matches if categorize_tier(j) == "Tier 1: Product Company / AI Startup"]
    tier2_strong = [j for j in strong_matches if categorize_tier(j) == "Tier 2: Global Enterprise / IT Services"]
    tier3_strong = [j for j in strong_matches if categorize_tier(j) == "Tier 3: Staffing Agency / Unverified"]

    now_str = datetime.now().strftime("%d %b %Y, %I:%M %p")
    
    md_content = f"""# Job Hunter Dashboard — {now_str}

## 📊 Summary Statistics
- **Total Scraped (Pending Match)**: {total_scraped}
- **Shortlisted Matches**: {total_shortlisted} (🔥 Strong: {len(strong_matches)} | 🟡 Possible: {len(possible_matches)})
  - 🌟 **Tier 1 (Product Companies & AI Startups)**: {len(tier1_strong)}
  - 🏢 **Tier 2 (Global Enterprises / Tech Services)**: {len(tier2_strong)}
  - 📋 **Tier 3 (Other / Staffing Agencies)**: {len(tier3_strong)}
- **Applied Positions**: {total_applied}
- **Rejected/Unfit Roles**: {total_rejected}

---

## 🌟 Tier 1: Product Companies & Verified AI Startups (High Priority)
*Direct engineering teams building AI, developer tooling, and modern backend systems.*

"""
    if not tier1_strong:
        md_content += "*No Tier 1 strong matches found in today's scrape.*\n\n"
    else:
        md_content += "| Score | Job ID | Company | Job Title | Location | Direct ATS Link | Source |\n"
        md_content += "| :---: | :--- | :--- | :--- | :--- | :---: | :--- |\n"
        for job in tier1_strong:
            url = job['job_url_direct'] or job['job_url'] or "#"
            url_text = "[Apply Direct ↗]" if job['job_url_direct'] else "[View Listing ↗]"
            md_content += f"| **{job['score']}%** | `{job['job_id']}` | **{job['company']}** | {job['title']} | {job['location']} | [{url_text}]({url}) | {job['site'].upper()} |\n"

    md_content += """
---

## 🏢 Tier 2: Global Enterprises & Established Tech Services
*Reputable MNCs, tech organizations, and global service firms.*

"""
    if not tier2_strong:
        md_content += "*No Tier 2 strong matches found.*\n\n"
    else:
        md_content += "| Score | Job ID | Company | Job Title | Location | Direct ATS Link | Source |\n"
        md_content += "| :---: | :--- | :--- | :--- | :--- | :---: | :--- |\n"
        for job in tier2_strong:
            url = job['job_url_direct'] or job['job_url'] or "#"
            url_text = "[Apply Direct ↗]" if job['job_url_direct'] else "[View Listing ↗]"
            md_content += f"| **{job['score']}%** | `{job['job_id']}` | **{job['company']}** | {job['title']} | {job['location']} | [{url_text}]({url}) | {job['site'].upper()} |\n"

    if tier3_strong:
        md_content += """
---

<details>
<summary>📋 <b>Tier 3: Staffing Agencies & Unverified Aggregators (Click to expand)</b></summary>

| Score | Job ID | Company | Job Title | Location | Source |
| :---: | :--- | :--- | :--- | :--- | :--- |
"""
        for job in tier3_strong:
            md_content += f"| {job['score']}% | `{job['job_id']}` | {job['company']} | {job['title']} | {job['location']} | {job['site'].upper()} |\n"
        md_content += "\n</details>\n"

    md_content += "\n### 📝 Strong Matches — Technical Evidence & Notes\n"
    for job in tier1_strong + tier2_strong:
        url = job['job_url_direct'] or job['job_url'] or "#"
        md_content += f"""#### 💻 {job['title']} — **{job['company']}** ({job['location']})
- **Job ID**: `{job['job_id']}`
- **Compatibility Score**: **{job['score']}%**
- **ATS Apply Link**: {url}
- **Source**: {job['site'].upper()} | **Job Type**: {job['job_type'] or 'N/A'}
- **Matching Notes**:
  {job['matching_notes']}
- **Evidence**:
  {job['evidence']}
  
---
"""

    md_content += """
## 🟡 Possible Matches (Score 75% - 84%)
*These are general CSE roles that may not match your resume perfectly, but are solid entry-level/intern opportunities.*

"""
    if not possible_matches:
        md_content += "No possible matches found today.\n\n"
    else:
        md_content += "| Score | Job ID | Company | Job Title | Location | Direct ATS Link | Source |\n"
        md_content += "| :---: | :--- | :--- | :--- | :--- | :---: | :--- |\n"
        for job in possible_matches:
            url = job['job_url_direct'] or job['job_url'] or "#"
            url_text = "[Apply Direct ↗]" if job['job_url_direct'] else "[View Listing ↗]"
            md_content += f"| **{job['score']}%** | `{job['job_id']}` | {job['company']} | {job['title']} | {job['location']} | [{url_text}]({url}) | {job['site'].upper()} |\n"
        
        md_content += "\n### Details & Matching Evidence\n"
        for job in possible_matches:
            url = job['job_url_direct'] or job['job_url'] or "#"
            md_content += f"""#### 💻 {job['title']} — **{job['company']}** ({job['location']})
- **Job ID**: `{job['job_id']}`
- **Compatibility Score**: **{job['score']}%**
- **ATS Apply Link**: {url}
- **Source**: {job['site'].upper()}
- **Matching Notes**:
  {job['matching_notes']}
- **Evidence**:
  {job['evidence']}
  
---
"""

    md_content += """
## 📁 Applied Positions
*A complete record of the positions you have submitted applications for.*

"""
    if not applied:
        md_content += "*No positions marked as applied yet.*\n"
    else:
        md_content += "| Date Applied | Company | Job Title | Location | Tailored Materials |\n"
        md_content += "| :--- | :--- | :--- | :--- | :--- |\n"
        for job in applied:
            resume_link = f"[Tailored Resume]({job['tailored_resume_path']})" if job['tailored_resume_path'] else "Original"
            cover_link = f"[Cover Letter]({job['tailored_cover_letter_path']})" if job['tailored_cover_letter_path'] else "N/A"
            materials = f"{resume_link} | {cover_link}"
            md_content += f"| {job['created_at'][:10]} | {job['company']} | {job['title']} | {job['location']} | {materials} |\n"

    # Write latest dashboard file and dated archive
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dashboard_path = os.path.join(base_dir, "dashboard.md")
    with open(dashboard_path, "w", encoding="utf-8") as f:
        f.write(md_content)
        
    # Save dated copy in dashboards/ directory
    dashboards_dir = os.path.join(base_dir, "dashboards")
    os.makedirs(dashboards_dir, exist_ok=True)
    date_filename = f"dashboard-{datetime.now().strftime('%Y-%m-%d')}.md"
    dated_path = os.path.join(dashboards_dir, date_filename)
    with open(dated_path, "w", encoding="utf-8") as f:
        f.write(md_content)
        
    print(f"Latest Dashboard saved at: {dashboard_path}")
    print(f"Dated Archive saved at: {dated_path}")
    return dashboard_path

if __name__ == "__main__":
    generate_dashboard()
