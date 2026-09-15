"""Backfill missing job descriptions for shortlisted and applied jobs.

Fetches the full description using the guest endpoint, saves it to SQLite,
runs deterministic screening safeguards, and rejects any jobs requiring 3+ years
experience, wrong graduation batches, or closed postings.
"""

import concurrent.futures
import sqlite3
import sys
import time
from typing import Dict, Any

import db
from matcher import fetch_description_from_web
from screening import deterministic_hard_filter, classify_company_tier
from quality import assess_listing_quality, quality_gate


def process_shortlisted_job(job: Dict[str, Any]) -> Dict[str, Any]:
    time.sleep(0.25)
    job_id = job["job_id"]
    title = job["title"]
    company = job["company"]
    site = job.get("site") or "linkedin"
    url = job.get("job_url_direct") or job.get("job_url") or ""

    desc = fetch_description_from_web(url, site, job_id=job_id)
    
    if desc == "EXPIRED_OR_CLOSED":
        return {
            "job_id": job_id,
            "action": "reject",
            "reason": f"Listing is closed / no longer accepting applications on {site.upper()}.",
            "description": None,
        }
    
    if not desc:
        # If unable to retrieve after multiple attempts, assess if title-only passes quality gate
        job_for_quality = dict(job)
        job_for_quality["description"] = ""
        company_tier = classify_company_tier(company)
        quality = assess_listing_quality(job_for_quality, company_tier)
        passes_q, q_reason = quality_gate(job_for_quality, company_tier, quality)
        if not passes_q:
            return {
                "job_id": job_id,
                "action": "reject",
                "reason": f"No JD available and failed quality gate: {q_reason}",
                "description": "",
            }
        return {
            "job_id": job_id,
            "action": "keep",
            "description": "",
        }

    # We got a description! Test deterministic filters
    job_eval = dict(job)
    job_eval["description"] = desc
    passes_hard, hard_reason = deterministic_hard_filter(job_eval)
    if not passes_hard:
        return {
            "job_id": job_id,
            "action": "reject",
            "reason": hard_reason,
            "description": desc,
        }

    company_tier = classify_company_tier(company)
    quality = assess_listing_quality(job_eval, company_tier)
    passes_q, q_reason = quality_gate(job_eval, company_tier, quality)
    if not passes_q:
        return {
            "job_id": job_id,
            "action": "reject",
            "reason": q_reason,
            "description": desc,
        }

    return {
        "job_id": job_id,
        "action": "update_jd",
        "description": desc,
    }


def process_applied_job(job: Dict[str, Any]) -> Dict[str, Any]:
    job_id = job["job_id"]
    site = job.get("site") or "linkedin"
    url = job.get("job_url_direct") or job.get("job_url") or ""

    desc = fetch_description_from_web(url, site, job_id=job_id)
    if desc and desc != "EXPIRED_OR_CLOSED":
        return {
            "job_id": job_id,
            "description": desc,
        }
    return {"job_id": job_id, "description": None}


def run_backfill(max_workers: int = 3):
    print("=" * 60)
    print("🚀 STARTING JOB DESCRIPTION BACKFILL & SAFEGUARD SCREENING")
    print("=" * 60)

    conn = db.get_db_connection()
    cursor = conn.cursor()
    
    # 1. Fetch shortlisted jobs with missing descriptions
    cursor.execute("""
    SELECT job_id, site, job_url, job_url_direct, title, company, location,
           date_posted, job_type, experience_range, description
    FROM jobs
    WHERE status = 'shortlisted' AND (description IS NULL OR description = '')
    """)
    shortlisted_jobs = [dict(r) for r in cursor.fetchall()]
    conn.close()

    total = len(shortlisted_jobs)
    print(f"Found {total} shortlisted jobs needing JD retrieval and screening.")

    rejected_count = 0
    updated_count = 0
    unchanged_count = 0

    rejections_by_reason = {}

    start_time = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_job = {executor.submit(process_shortlisted_job, j): j for j in shortlisted_jobs}
        
        done_count = 0
        for future in concurrent.futures.as_completed(future_to_job):
            done_count += 1
            original_job = future_to_job[future]
            try:
                res = future.result()
            except Exception as e:
                print(f"Error processing {original_job['job_id']}: {e}", file=sys.stderr)
                continue

            action = res.get("action")
            job_id = res["job_id"]
            
            conn = db.get_db_connection()
            c = conn.cursor()
            try:
                if action == "reject":
                    reason = res["reason"]
                    desc = res.get("description") or ""
                    c.execute("""
                    UPDATE jobs
                    SET status = 'rejected', score = 0, evidence = '',
                        matching_notes = ?, description = CASE WHEN ? != '' THEN ? ELSE description END
                    WHERE job_id = ?
                    """, (f"REJECTED: {reason}", desc, desc, job_id))
                    conn.commit()
                    rejected_count += 1
                    rejections_by_reason[reason] = rejections_by_reason.get(reason, 0) + 1
                    print(f"[{done_count}/{total}] ❌ REJECTED {original_job['title']} at {original_job['company']}: {reason}")
                elif action == "update_jd":
                    desc = res["description"]
                    c.execute("UPDATE jobs SET description = ? WHERE job_id = ?", (desc, job_id))
                    conn.commit()
                    updated_count += 1
                    print(f"[{done_count}/{total}] ✅ KEPT & UPDATED JD ({len(desc)} chars): {original_job['title']} at {original_job['company']}")
                else:
                    unchanged_count += 1
            finally:
                conn.close()

    elapsed = time.time() - start_time
    print("-" * 60)
    print(f"Shortlisted Processing Complete in {elapsed:.1f}s!")
    print(f"-> Total Processed: {total}")
    print(f"-> Rejected by Safeguards: {rejected_count}")
    print(f"-> Verified & Updated JD: {updated_count}")
    print(f"-> Kept Unchanged: {unchanged_count}")
    print("\nRejection Breakdown:")
    for r, cnt in sorted(rejections_by_reason.items(), key=lambda x: x[1], reverse=True):
        print(f"  - {cnt} roles: {r}")

    # 2. Backfill Applied Jobs (JD only, don't change status)
    conn = db.get_db_connection()
    c = conn.cursor()
    c.execute("""
    SELECT job_id, site, job_url, job_url_direct, title, company
    FROM jobs
    WHERE status = 'applied' AND (description IS NULL OR description = '')
    """)
    applied_jobs = [dict(r) for r in c.fetchall()]
    conn.close()

    if applied_jobs:
        print(f"\nBackfilling {len(applied_jobs)} applied jobs with full JDs...")
        applied_updated = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_applied = {executor.submit(process_applied_job, j): j for j in applied_jobs}
            for future in concurrent.futures.as_completed(future_to_applied):
                res = future.result()
                if res.get("description"):
                    conn = db.get_db_connection()
                    c = conn.cursor()
                    c.execute("UPDATE jobs SET description = ? WHERE job_id = ?", (res["description"], res["job_id"]))
                    conn.commit()
                    conn.close()
                    applied_updated += 1
        print(f"-> Backfilled {applied_updated} applied job descriptions.")

    print("\n" + "=" * 60)
    print("🎉 ALL BACKFILL OPERATIONS FINISHED!")
    print("=" * 60)


if __name__ == "__main__":
    run_backfill()
