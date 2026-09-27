import json
import os
import pandas as pd
import db

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

    df = pd.DataFrame(jobs_list)
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
