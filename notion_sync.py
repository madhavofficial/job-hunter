"""Two-way Notion Application Tracker Synchronizer.

Syncs applied software applications between jobs.db and the Notion
"Off-Campus Job Applications Tracker" database.
"""

import os
import re
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import requests
from dotenv import load_dotenv

import db

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID", "3c3ff93a-7912-8151-bccd-c51bc49f0e71")
NOTION_VERSION = "2022-06-28"

VALID_PLATFORMS = {
    "Workday", "Greenhouse", "SmartRecruiters", "LinkedIn",
    "Oracle Cloud", "iCIMS", "Ashby", "Keka", "Direct Portal"
}

VALID_STATUSES = {
    "Applied", "Under Review", "Assessment / OA", "Interview",
    "Account Created", "Rejected", "Assessment Received",
    "Recruiter Reviewing", "In Consideration", "Under Consideration"
}


def get_headers() -> Dict[str, str]:
    token = os.getenv("NOTION_TOKEN")
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json"
    }


def is_notion_configured() -> bool:
    token = os.getenv("NOTION_TOKEN")
    return bool(token and token.startswith("ntn_"))


def map_platform(url: str, site: str = "") -> str:
    url_l = (url or "").lower()
    site_l = (site or "").lower()
    if "myworkdayjobs.com" in url_l or "workday" in url_l:
        return "Workday"
    if "greenhouse.io" in url_l or "gh_jid" in url_l:
        return "Greenhouse"
    if "smartrecruiters.com" in url_l:
        return "SmartRecruiters"
    if "linkedin.com" in url_l or site_l == "linkedin":
        return "LinkedIn"
    if "oraclecloud.com" in url_l or "taleo.net" in url_l or "oracle" in url_l:
        return "Oracle Cloud"
    if "icims.com" in url_l:
        return "iCIMS"
    if "ashbyhq.com" in url_l:
        return "Ashby"
    if "keka.com" in url_l:
        return "Keka"
    return "Direct Portal"


def fetch_all_notion_applications() -> Tuple[List[dict], int]:
    """Fetches all entries from Notion database and returns (entries, max_sno)."""
    if not is_notion_configured():
        return [], 0

    headers = get_headers()
    database_id = os.getenv("NOTION_DATABASE_ID", NOTION_DATABASE_ID)
    url = f"https://api.notion.com/v1/databases/{database_id}/query"

    entries = []
    has_more = True
    start_cursor = None
    max_sno = 0

    while has_more:
        payload = {"page_size": 100}
        if start_cursor:
            payload["start_cursor"] = start_cursor

        res = requests.post(url, headers=headers, json=payload, timeout=20)
        if res.status_code != 200:
            print(f"Warning: Notion query failed with code {res.status_code}: {res.text}", file=sys.stderr)
            break

        data = res.json()
        results = data.get("results", [])
        entries.extend(results)

        for p in results:
            sno_val = p.get("properties", {}).get("S.No", {}).get("number")
            if sno_val and isinstance(sno_val, (int, float)) and sno_val > max_sno:
                max_sno = int(sno_val)

        has_more = data.get("has_more", False)
        start_cursor = data.get("next_cursor")

    return entries, max_sno


def push_job_to_notion(job: dict, sno: int) -> Optional[str]:
    """Pushes a single applied job from jobs.db to the Notion Application Tracker."""
    if not is_notion_configured():
        return None

    headers = get_headers()
    database_id = os.getenv("NOTION_DATABASE_ID", NOTION_DATABASE_ID)
    create_url = "https://api.notion.com/v1/pages"

    company = (job.get("company") or "Unknown Company").strip()
    title = (job.get("title") or "Software Engineer").strip()
    job_url = (job.get("job_url_direct") or job.get("job_url") or "").strip()
    job_id = (job.get("job_id") or "").strip()
    site = (job.get("site") or "").strip()

    # Determine date applied
    today_str = datetime.now().strftime("%Y-%m-%d")
    date_val = today_str
    created_at = job.get("created_at") or ""
    if created_at and len(created_at) >= 10:
        date_candidate = created_at[:10]
        if re.match(r"^\d{4}-\d{2}-\d{2}$", date_candidate):
            date_val = date_candidate

    platform = map_platform(job_url, site)

    properties = {
        "Company": {
            "title": [{"text": {"content": company[:100]}}]
        },
        "Role": {
            "rich_text": [{"text": {"content": title[:100]}}]
        },
        "Status": {
            "select": {"name": "Applied"}
        },
        "Platform / ATS": {
            "select": {"name": platform}
        },
        "S.No": {
            "number": sno
        },
        "Date Applied": {
            "date": {"start": date_val}
        }
    }

    if job_url.startswith("http://") or job_url.startswith("https://"):
        properties["Job Listing Link"] = {"url": job_url}

    if job_id:
        properties["Req ID / Job ID"] = {
            "rich_text": [{"text": {"content": job_id[:100]}}]
        }

    body = {
        "parent": {"database_id": database_id},
        "properties": properties
    }

    try:
        res = requests.post(create_url, headers=headers, json=body, timeout=20)
        if res.status_code in (200, 201):
            created_page = res.json()
            return created_page.get("id")
        else:
            print(f"Warning: Failed to create Notion entry for {company}: {res.status_code} {res.text}", file=sys.stderr)
            return None
    except Exception as e:
        print(f"Warning: Exception while pushing {company} to Notion: {e}", file=sys.stderr)
        return None


def sync_applied_to_notion(target_job_id: str = None) -> int:
    """Syncs applied jobs from jobs.db to Notion tracker.
    
    If target_job_id is provided, syncs that specific job.
    If None, scans all applied jobs and adds missing ones.
    """
    if not is_notion_configured():
        return 0

    print(f"\n====================================================")
    print(f"🔄 SYNCHRONIZING APPLICATIONS WITH NOTION TRACKER")
    print(f"====================================================")

    existing_entries, max_sno = fetch_all_notion_applications()
    print(f"-> Found {len(existing_entries)} existing applications in Notion (Highest S.No: {max_sno}).")

    notion_urls = set()
    notion_req_ids = set()
    notion_companies = set()

    for p in existing_entries:
        props = p.get("properties", {})
        u = props.get("Job Listing Link", {}).get("url")
        if u:
            notion_urls.add(u.strip())
        
        req_arr = props.get("Req ID / Job ID", {}).get("rich_text", [])
        if req_arr:
            req_id_str = req_arr[0].get("plain_text", "").strip()
            if req_id_str:
                notion_req_ids.add(req_id_str)

        co_arr = props.get("Company", {}).get("title", [])
        if co_arr:
            co_str = co_arr[0].get("plain_text", "").strip().lower()
            if co_str:
                notion_companies.add(co_str)

    conn = db.get_db_connection()
    cursor = conn.cursor()

    if target_job_id:
        cursor.execute("""
            SELECT job_id, company, title, date_posted, job_url, job_url_direct, site, created_at
            FROM jobs
            WHERE job_id = ? AND status = 'applied'
        """, (target_job_id,))
        jobs_to_sync = [dict(r) for r in cursor.fetchall()]
    else:
        cursor.execute("""
            SELECT job_id, company, title, date_posted, job_url, job_url_direct, site, created_at
            FROM jobs
            WHERE status = 'applied'
            ORDER BY created_at ASC
        """)
        jobs_to_sync = [dict(r) for r in cursor.fetchall()]

    conn.close()

    synced_count = 0
    current_sno = max_sno

    for j in jobs_to_sync:
        u1 = (j.get("job_url") or "").strip()
        u2 = (j.get("job_url_direct") or "").strip()
        jid = (j.get("job_id") or "").strip()
        co_lower = (j.get("company") or "").strip().lower()

        # Check if already present in Notion
        already_in_notion = False
        if jid and jid in notion_req_ids:
            already_in_notion = True
        elif u1 and u1 in notion_urls:
            already_in_notion = True
        elif u2 and u2 in notion_urls:
            already_in_notion = True

        if already_in_notion:
            continue

        current_sno += 1
        page_id = push_job_to_notion(j, current_sno)
        if page_id:
            print(f"✓ [S.No {current_sno}] Added to Notion: {j['company']} — {j['title']} ({j['job_id']})")
            synced_count += 1
            if u1: notion_urls.add(u1)
            if u2: notion_urls.add(u2)
            if jid: notion_req_ids.add(jid)
            time.sleep(0.35)  # Notion rate-limit etiquette

    print(f"-> Notion sync complete: {synced_count} new applications created in tracker.")
    return synced_count


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1]:
        sync_applied_to_notion(sys.argv[1])
    else:
        sync_applied_to_notion()
