import sys
import pandas as pd
from jobspy import scrape_jobs
import db

import os
import re
import random
import time

DEFAULT_SEARCH_TERMS = [
    "Software Engineer Intern",
    "Software Developer Intern",
    "Backend Developer Intern",
    "Python Developer",
    "Junior Software Engineer",
    "Junior Backend Engineer",
    "Junior AI Engineer",
    "Machine Learning Intern",
    "FastAPI Developer",
    "Associate Software Engineer"
]

# JobSpy's Glassdoor adapter cannot resolve the country-wide "India" location
# used by this pipeline, and its ZipRecruiter adapter only supports US/Canada.
# Keep the source list explicit so unsupported boards do not generate noisy,
# predictable failures on every query.
SUPPORTED_INDIA_SITES = ("indeed", "linkedin")

def get_dynamic_search_terms():
    """Dynamically parses resume.md to build relevant search queries based on the candidate's active stack and career objective."""
    resume_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resume.md")
    if not os.path.exists(resume_path):
        return DEFAULT_SEARCH_TERMS

    with open(resume_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Extract target domains and stack from resume
    terms = set()
    
    # Standard role prefixes
    levels = ["Intern", "Junior", "Associate", "Developer"]
    
    # Key technologies mentioned in the candidate's skills / experience
    core_techs = []
    if "Python" in content: core_techs.append("Python")
    if "FastAPI" in content or "Backend" in content: core_techs.append("Backend Developer")
    if "AI" in content or "LLM" in content or "LangChain" in content: core_techs.append("AI Engineer")
    if "Machine Learning" in content or "PyTorch" in content: core_techs.append("Machine Learning")
    if "Software Engineering" in content: core_techs.append("Software Engineer")

    # Generate combinatorial targeted queries
    for tech in core_techs:
        if "Engineer" in tech or "Developer" in tech:
            terms.add(f"Junior {tech}")
            terms.add(f"{tech} Intern")
        else:
            terms.add(f"{tech} Intern")
            terms.add(f"Junior {tech} Engineer")

    # Always ensure fundamental software engineering queries are included
    terms.update([
        "Software Engineer Intern",
        "Software Developer Intern",
        "Junior Software Engineer",
        "Python Backend Developer",
        "Junior AI Engineer",
        "Backend Developer Intern",
        "Associate Software Engineer",
        "6 month internship software"
    ])

    return sorted(list(terms))

def run_collector(limit_per_query=15, hours_old=72):
    db.init_db()
    total_new_jobs = 0
    
    print(f"Starting job collection for the last {hours_old} hours...")
    
    sites = list(SUPPORTED_INDIA_SITES)
    print(f"Using India-compatible sources: {', '.join(sites)}")
    
    search_terms = get_dynamic_search_terms()
    print(f"Loaded {len(search_terms)} dynamic search queries derived from your resume profile.")
    
    for index, term in enumerate(search_terms):
        print(f"\nSearching for: '{term}' in India...")
        try:
            # We call scrape_jobs. If LinkedIn or another site blocks, jobspy might throw an exception 
            # or return partial results. We catch exceptions per query to ensure the collector continues.
            jobs = scrape_jobs(
                site_name=sites,
                search_term=term,
                location="India",
                results_wanted=limit_per_query,
                hours_old=hours_old,
                country_indeed='india'
            )
            
            if not jobs.empty:
                new_count = db.add_jobs(jobs)
                total_new_jobs += new_count
                print(f"-> Found {len(jobs)} jobs. Inserted {new_count} new unique jobs.")
            else:
                print("-> No jobs found for this query.")
                
        except Exception as e:
            print(f"-> Error searching for '{term}': {e}", file=sys.stderr)
            # If a site is aggressively blocking, we can try to fall back to just indeed
            print("Retrying with Indeed only...")
            try:
                jobs = scrape_jobs(
                    site_name=["indeed"],
                    search_term=term,
                    location="India",
                    results_wanted=limit_per_query,
                    hours_old=hours_old,
                    country_indeed='india'
                )
                if not jobs.empty:
                    new_count = db.add_jobs(jobs)
                    total_new_jobs += new_count
                    print(f"-> [Fallback] Found {len(jobs)} jobs. Inserted {new_count} new unique jobs.")
            except Exception as fallback_err:
                print(f"-> [Fallback Error] Failed: {fallback_err}", file=sys.stderr)

        if index < len(search_terms) - 1:
            time.sleep(random.uniform(2.5, 5.5))

    print(f"\nJob collection complete. Total new unique jobs stored: {total_new_jobs}")
    return total_new_jobs

if __name__ == "__main__":
    limit = 15
    hours = 72
    if len(sys.argv) > 1:
        limit = int(sys.argv[1])
    if len(sys.argv) > 2:
        hours = int(sys.argv[2])
    run_collector(limit, hours)
