"""
Placement Drive Resume Curation Bridge for job-hunter.

Directly callable utility to curate, tailor, and compile a single-page ATS-optimized
resume for a specific placement company, role title, and extracted job description.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import db
import tailor


def curate_for_placement(company: str, title: str, jd_text: str, profile_name: str = "madhav") -> str:
    """Ingests placement drive details and invokes tailor_materials."""
    db.init_db()

    clean_key = "".join(c for c in f"{company}_{title}".lower().replace(" ", "_") if c.isalnum() or c == "_")[:40]
    digest = hashlib.md5(jd_text.encode("utf-8", errors="ignore")).hexdigest()[:8]
    job_id = f"placement_{clean_key}_{digest}"

    conn = db.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT OR REPLACE INTO jobs (
        job_id, site, job_url, title, company, description, status, created_at
    ) VALUES (?, 'pesu_placement', 'https://placements.4gd.ai', ?, ?, ?, 'discovered', datetime('now'))
    """, (job_id, title, company, jd_text))
    conn.commit()
    conn.close()

    res = tailor.tailor_materials(job_id, profile_name=profile_name)
    if res and len(res) >= 2:
        return res[1]  # Returns resume_pdf_filepath
    return ""


def main():
    parser = argparse.ArgumentParser(description="Curate placement resume")
    parser.add_argument("--company", required=True, help="Company name")
    parser.add_argument("--title", required=True, help="Position/role title")
    parser.add_argument("--jd-file", required=True, help="Path to extracted job description text file")
    parser.add_argument("--profile", default="madhav", help="Candidate profile ID")

    args = parser.parse_args()

    if not os.path.exists(args.jd_file):
        print(f"Error: JD file {args.jd_file} not found", file=sys.stderr)
        sys.exit(1)

    with open(args.jd_file, "r", encoding="utf-8") as f:
        jd_content = f.read()

    pdf_path = curate_for_placement(args.company, args.title, jd_content, profile_name=args.profile)
    if pdf_path and os.path.exists(pdf_path):
        print(f"CURATED_PDF_PATH:{pdf_path}")
        sys.exit(0)
    else:
        print("ERROR: Failed to curate resume", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
