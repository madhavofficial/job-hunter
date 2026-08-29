"""Sync applied applications from Notion Off-Campus Job Applications Tracker into jobs.db."""

import json
import os
import re
import db

NOTION_DATA_FILE = "/Users/madhavjayam/.gemini/antigravity-cli/brain/ac14f0c0-cc95-4569-8285-d8e3915ae0c5/.system_generated/steps/1463/output.txt"


def sync_notion():
    db.init_db()
    with open(NOTION_DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    results = data.get("results", [])
    print(f"Loaded {len(results)} applications from Notion tracker.\n")

    conn = db.get_db_connection()
    cursor = conn.cursor()

    updated_count = 0
    inserted_count = 0

    for item in results:
        props = item.get("properties", {})

        # 1. Company
        company_objs = props.get("Company", {}).get("title", [])
        company = company_objs[0].get("plain_text", "").strip() if company_objs else ""

        # 2. Role / Title
        role_objs = props.get("Role", {}).get("rich_text", [])
        role = role_objs[0].get("plain_text", "").strip() if role_objs else ""

        # 3. URL
        url = props.get("Job Listing Link", {}).get("url", "") or ""

        # 4. Date Applied
        date_applied = ""
        date_prop = props.get("Date Applied", {}).get("date")
        if date_prop and date_prop.get("start"):
            date_applied = date_prop["start"]

        # 5. Status
        status_select = props.get("Status", {}).get("select")
        status_name = status_select.get("name", "Applied") if status_select else "Applied"

        # Map Notion status to jobs.db status
        db_status = "applied"
        if status_name.lower() in ["rejected", "not selected"]:
            db_status = "rejected"
        else:
            db_status = "applied"

        # Search for existing job in DB
        found_job = None
        if url:
            cursor.execute("SELECT job_id, title, company, status FROM jobs WHERE job_url = ? OR job_url_direct = ?", (url, url))
            found_job = cursor.fetchone()

            if not found_job and "linkedin.com/jobs/view/" in url:
                m = re.search(r"view/(\d+)", url)
                if m:
                    lid = f"li-{m.group(1)}"
                    cursor.execute("SELECT job_id, title, company, status FROM jobs WHERE job_id = ?", (lid,))
                    found_job = cursor.fetchone()

        if not found_job and company and role:
            cursor.execute("SELECT job_id, title, company, status FROM jobs WHERE lower(company) = lower(?) AND lower(title) = lower(?)", (company, role))
            found_job = cursor.fetchone()

        if not found_job and company:
            cursor.execute("SELECT job_id, title, company, status FROM jobs WHERE lower(company) = lower(?)", (company,))
            found_job = cursor.fetchone()

        if found_job:
            cursor.execute("UPDATE jobs SET status = ? WHERE job_id = ?", (db_status, found_job["job_id"]))
            print(f"✓ Updated existing job [{found_job['job_id']}] {found_job['company']} -> status='{db_status}'")
            updated_count += 1
        else:
            # Generate deterministic ID
            item_id = item["id"].replace("-", "")[:12]
            job_id = f"notion-{item_id}"
            cursor.execute("""
            INSERT OR REPLACE INTO jobs (
                job_id, site, job_url, job_url_direct, title, company, location,
                date_posted, job_type, description, is_remote, skills, experience_range,
                score, status, matching_notes, created_at
            ) VALUES (?, 'notion', ?, ?, ?, ?, 'India / Remote', ?, 'Full-time', '', 0, '', '', 95, ?, 'Imported from Notion Application Tracker', datetime('now'))
            """, (job_id, url, url, role or "Software Engineer", company, date_applied or "Recent", db_status))
            print(f"+ Inserted new applied record [{job_id}] {company} ({role}) -> status='{db_status}'")
            inserted_count += 1

    conn.commit()
    conn.close()

    print(f"\n=======================================================")
    print(f"✅ Notion Sync Completed:")
    print(f"   • Total Notion entries processed: {len(results)}")
    print(f"   • Existing database jobs marked as applied: {updated_count}")
    print(f"   • New applied tracker entries created: {inserted_count}")
    print(f"=======================================================")


if __name__ == "__main__":
    sync_notion()
