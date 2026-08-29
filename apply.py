"""Interactive Application CLI with interactive numbered menu and 1-click batch support."""

import os
import sys
import webbrowser

import db
import tailor
from screening import classify_company_tier


def apply_single_job(job_id: str):
    db.init_db()
    conn = db.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
    job = cursor.fetchone()
    conn.close()

    if not job:
        print(f"Error: Job ID '{job_id}' not found in database.", file=sys.stderr)
        return False

    title = job["title"]
    company = job["company"]
    location = job["location"]
    url = job["job_url_direct"] or job["job_url"]

    print("====================================================")
    print("              INTERACTIVE APPLY PIPELINE            ")
    print("====================================================")
    print(f"Job: '{title}' at '{company}' ({location})")
    print(f"Target URL: {url}")
    print("====================================================")
    print("Step 1: Generating Tailored Resume (Markdown & ATS PDF)...")

    materials = tailor.tailor_materials(job_id)
    if materials and len(materials) >= 2:
        resume_path, resume_pdf_path = materials[0], materials[1]
    else:
        resume_path = resume_pdf_path = None

    if not resume_path:
        print("Error: Failed to generate tailored resume. Aborting.", file=sys.stderr)
        return False

    print("\nStep 2: Review generated files:")
    print(f"-> Tailored Resume:      file://{resume_path}")
    print(f"-> ATS Resume PDF:       file://{resume_pdf_path}")
    print("====================================================")

    if url:
        print(f"Opening browser to: {url}")
        webbrowser.open(url)
    else:
        print("Warning: No target URL available to open.")

    print("\nDid you submit the application? [Y]es (mark as applied) / [S]kip / [E]xpired:")
    while True:
        answer = input("> ").strip().lower()
        if answer in {"y", "s", "e"}:
            break
        print("Please enter Y, S, or E.")

    if answer == "y":
        db.mark_as_applied(job_id, resume_path, None, resume_pdf_path, None)
        status_message = "Application marked as applied."
    elif answer == "e":
        db.mark_as_rejected(job_id)
        status_message = "Listing marked as rejected (expired)."
    else:
        db.mark_as_shortlisted(job_id)
        status_message = "Application skipped; job remains shortlisted."

    print("\n====================================================")
    print("🎉 Action Checklist:")
    print(f"1. Target URL opened for '{title}' at '{company}'.")
    print(f"2. ATS Resume PDF ready at:")
    print(f"   {resume_pdf_path}")
    print(f"3. {status_message}")
    print("====================================================")
    return True


def interactive_menu():
    db.init_db()
    conn = db.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT job_id, title, company, location, score, date_posted, created_at
    FROM jobs
    WHERE status = 'shortlisted'
    ORDER BY created_at DESC, score DESC
    LIMIT 25
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    valid_jobs = [r for r in rows if not classify_company_tier(r["company"]).startswith("Tier 3")][:15]

    if not valid_jobs:
        print("No active shortlisted jobs found in database.")
        print("Run 'python run.sh' to discover fresh opportunities.")
        return

    print("\n================================================================================")
    print("                      🔥 TOP FRESH SHORTLISTED JOBS                             ")
    print("================================================================================")
    for i, j in enumerate(valid_jobs, 1):
        tier = classify_company_tier(j["company"]).split(":")[0]
        date_str = j["date_posted"] if j["date_posted"] and j["date_posted"] != "nan" else "Recent"
        print(f" [{i:2d}] {j['score']}% | {j['company'][:20]:<20} | {j['title'][:32]:<32} | {tier} ({date_str})")
    print("================================================================================")
    print(" Commands: [1-15] Select job | [u] Custom Job URL | [w] Web UI | [c] Clear Stale | [q] Quit")
    print("================================================================================")

    choice = input("Enter choice: ").strip().lower()
    if choice == "q":
        return
    elif choice == "u":
        custom_url = input("Paste job listing URL: ").strip()
        if custom_url:
            import custom_job
            custom_job.process_custom_url(custom_url)
    elif choice == "w":
        import web_dashboard
        web_dashboard.start_server(open_browser=True)
    elif choice == "c":
        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        conn = db.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE jobs SET status = 'rejected' WHERE status = 'shortlisted' AND (created_at < ? OR created_at IS NULL)", (cutoff,))
        cnt = cursor.rowcount
        conn.commit()
        conn.close()
        print(f"✓ Archived {cnt} stale listings older than 7 days.")
    elif choice.isdigit() and 1 <= int(choice) <= len(valid_jobs):
        selected_job = valid_jobs[int(choice) - 1]
        apply_single_job(selected_job["job_id"])
    else:
        print("Invalid selection.")


def main():
    if len(sys.argv) >= 2:
        arg = sys.argv[1].strip()
        if arg.startswith("http://") or arg.startswith("https://"):
            import custom_job
            custom_job.process_custom_url(arg)
        else:
            apply_single_job(arg)
    else:
        interactive_menu()


if __name__ == "__main__":
    main()
