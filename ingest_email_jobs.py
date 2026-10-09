import json
import os
import pandas as pd
import db
from quality import GMAIL_ALERT_SITE, has_direct_employer_signal

_PREFILTER_NOTE = "not a direct India or worldwide employer posting"


def jobs_for_ingest(jobs_list: list) -> list:
    """Keep tuned Gmail alerts and any direct employer posting in the harvest file.

    LinkedIn cards from the alert mail are retagged as gmail. A LinkedIn or
    Indeed row from any other source is still dropped.
    """
    kept = []
    for job in jobs_list:
        if not isinstance(job, dict):
            continue
        site = str(job.get("site") or "").lower()
        if site in {"linkedin", GMAIL_ALERT_SITE}:
            row = dict(job)
            row["site"] = GMAIL_ALERT_SITE
            kept.append(row)
        elif has_direct_employer_signal(job):
            kept.append(job)
    return kept


def reopen_known_alert_copies(jobs: list) -> int:
    """Let an alert replace a stored LinkedIn copy of the same posting.

    Applied rows keep their status. A rejection for some other reason stays
    rejected. The aggregator prefilter is cleared so the matcher can score it.
    """
    conn = db.get_db_connection()
    cursor = conn.cursor()
    reopened = 0
    for job in jobs:
        if str(job.get("site") or "").lower() != GMAIL_ALERT_SITE:
            continue
        row = None
        job_id = str(job.get("job_id") or "")
        if job_id:
            row = cursor.execute(
                "SELECT job_id, site, status, matching_notes FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        url = job.get("job_url") or job.get("job_url_direct") or ""
        if row is None and url:
            row = cursor.execute(
                "SELECT job_id, site, status, matching_notes FROM jobs WHERE job_url = ? OR job_url_direct = ?",
                (url, url),
            ).fetchone()
        if row is None or str(row["site"] or "").lower() != "linkedin":
            continue
        status = str(row["status"] or "")
        notes = str(row["matching_notes"] or "")
        if status == "rejected" and _PREFILTER_NOTE in notes:
            cursor.execute(
                """
                UPDATE jobs
                SET site = ?, status = 'scraped', score = 0, evidence = '', matching_notes = ''
                WHERE job_id = ?
                """,
                (GMAIL_ALERT_SITE, row["job_id"]),
            )
            reopened += 1
        else:
            cursor.execute(
                "UPDATE jobs SET site = ? WHERE job_id = ?",
                (GMAIL_ALERT_SITE, row["job_id"]),
            )
            if status == "scraped":
                reopened += 1
    conn.commit()
    conn.close()
    return reopened


def ingest_harvested_jobs():
    db.init_db()
    json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "harvested_email_jobs.json")
    if not os.path.exists(json_path):
        print(f"Error: {json_path} does not exist.")
        return 0

    with open(json_path, "r", encoding="utf-8") as f:
        jobs_list = json.load(f)

    if not jobs_list:
        print("No jobs found in harvested JSON.")
        return 0

    kept = jobs_for_ingest(jobs_list)
    skipped = len(jobs_list) - len(kept)
    if skipped:
        print(f"Skipped {skipped} rows that are not Gmail alerts or direct employer postings.")
    if not kept:
        print("No Gmail alerts to ingest.")
        return 0
    reopened = reopen_known_alert_copies(kept)
    if reopened:
        print(f"Reopened {reopened} stored LinkedIn copies that arrived again as Gmail alerts.")

    df = pd.DataFrame(kept)
    # Ensure all required columns exist
    for col in ["site", "job_url", "job_url_direct", "title", "company", "location", "date_posted", "job_type", "description", "is_remote", "skills", "experience_range"]:
        if col not in df.columns:
            df[col] = ""

    inserted = db.add_jobs(df)
    print(f"\n========================================================")
    print(f"✓ Ingested {inserted} new unique jobs from Gmail alerts into jobs.db (out of {len(jobs_list)} total).")
    print(f"========================================================")
    return inserted

if __name__ == "__main__":
    ingest_harvested_jobs()
