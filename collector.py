import sys
import pandas as pd
from jobspy import scrape_jobs
import db

import os
import re
import random
import time

DEFAULT_SEARCH_TERMS = [
    # Modern High-Signal AI & ML Roles
    "Applied AI Engineer",
    "AI Engineer",
    "Generative AI Engineer",
    "LLM Engineer",
    "Machine Learning Engineer",
    "AI Intern",
    "Applied AI Intern",
    "Machine Learning Intern",
    # Core Software Engineering, SDE & Backend Roles
    "Software Development Engineer",
    "Software Engineer",
    "SDE 1",
    "Backend Engineer",
    "Backend Developer",
    "Python Backend Developer",
    "Python Developer",
    "FastAPI Developer",
    "Full Stack Developer",
    "Member of Technical Staff",
    "Associate Software Engineer",
    # Internships & Graduate Programs (Any city in India)
    "Software Engineer Intern",
    "Software Developer Intern",
    "Backend Developer Intern",
    "SDE Intern",
    "Graduate Engineer Trainee",
    "6 month internship software",
]

# Curated list of elite tech companies in India for targeted discovery
TARGET_TECH_COMPANIES = [
    "OpenAI",
    "Anthropic",
    "Google",
    "Microsoft",
    "Meta",
    "Apple",
    "Amazon",
    "NVIDIA",
    "Uber",
    "Stripe",
    "Razorpay",
    "Swiggy",
    "Zomato",
    "CRED",
    "Zepto",
    "Flipkart",
    "Postman",
    "Atlassian",
    "Databricks",
    "Snowflake",
    "Perplexity",
    "Scale AI",
    "Vercel",
    "Supabase",
    "Linear",
    "Salesforce",
    "Oracle",
    "Cisco",
    "Adobe",
    "Intuit",
    "PayPal",
    "Goldman Sachs",
    "Morgan Stanley",
    "JPMorganChase",
    "BNP Paribas",
]

# JobSpy's Glassdoor adapter cannot resolve the country-wide "India" location
# used by this pipeline, and its ZipRecruiter adapter only supports US/Canada.
# Keep the source list explicit so unsupported boards do not generate noisy,
# predictable failures on every query.
# JobSpy supports Naukri directly. Glassdoor and Monster are intentionally not
# listed here: this installed JobSpy release has no reliable India Monster
# adapter, and Glassdoor currently returns 400s for this pipeline's query shape.
SUPPORTED_INDIA_SITES = ("indeed", "linkedin", "naukri")

def get_dynamic_search_terms():
    """Dynamically parses resume.md to build relevant search queries based on the candidate's active stack and career objective."""
    resume_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resume.md")
    if not os.path.exists(resume_path):
        return DEFAULT_SEARCH_TERMS

    with open(resume_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Extract target domains and stack from resume
    terms = set()
    
    # Key technologies and domains from candidate's profile
    core_techs = []
    if "Python" in content: core_techs.append("Python Developer")
    if "FastAPI" in content or "Backend" in content: core_techs.append("Backend Engineer")
    if "AI" in content or "LLM" in content or "LangChain" in content: core_techs.append("Applied AI Engineer")
    if "Machine Learning" in content or "PyTorch" in content: core_techs.append("Machine Learning Engineer")
    if "Software Engineering" in content: core_techs.append("Software Engineer")

    # Generate targeted combinations (direct title, intern, associate, junior)
    for tech in core_techs:
        terms.add(tech)
        terms.add(f"{tech} Intern")
        terms.add(f"Junior {tech}")
        terms.add(f"Associate {tech}")

    # Always ensure fundamental high-signal software engineering and AI queries are included
    terms.update([
        "Applied AI Engineer",
        "AI Engineer",
        "Generative AI Engineer",
        "Machine Learning Engineer",
        "Software Development Engineer",
        "SDE 1",
        "Software Engineer",
        "Backend Engineer",
        "Python Backend Developer",
        "Full Stack Developer",
        "Member of Technical Staff",
        "Software Engineer Intern",
        "Software Developer Intern",
        "Backend Developer Intern",
        "Machine Learning Intern",
        "AI Intern",
        "Associate Software Engineer",
        "Graduate Engineer Trainee",
        "6 month internship software",
    ])

    return sorted(list(terms))

def run_company_collector(companies=None, limit_per_company=15, hours_old=None, location="India"):
    """Targeted collector for tier-1 tech giants, decacorns, and unicorns.
    
    Directly scrapes target company openings on LinkedIn and Indeed in India,
    guaranteeing that top-tier postings (e.g. OpenAI, Anthropic, Google, Uber, Razorpay)
    are discovered immediately rather than hoping generic queries rank them.
    """
    db.init_db()
    total_new = 0
    target_list = companies or TARGET_TECH_COMPANIES
    sites = ["linkedin", "indeed"]
    
    print(f"\n====================================================")
    print(f"🎯 INITIATING TARGETED TIER-1 COMPANY SCRAPER")
    print(f"Targeting {len(target_list)} elite tech companies in {location}")
    print(f"====================================================")
    
    for idx, company in enumerate(target_list):
        print(f"\n[{idx+1}/{len(target_list)}] Searching company: '{company}' in {location}...")
        try:
            kwargs = {"hours_old": hours_old} if hours_old else {}
            jobs = scrape_jobs(
                site_name=sites,
                search_term=company,
                location=location,
                results_wanted=limit_per_company,
                country_indeed='india',
                **kwargs
            )
            if not jobs.empty:
                # Filter down to jobs matching the company name to avoid keyword pollution
                comp_lower = company.lower()
                company_jobs = jobs[jobs['company'].astype(str).str.lower().str.contains(comp_lower, na=False)]
                jobs_to_insert = company_jobs if not company_jobs.empty else jobs

                new_cnt = db.add_jobs(jobs_to_insert)
                total_new += new_cnt
                print(f"-> Found {len(jobs_to_insert)} jobs for {company}. Inserted {new_cnt} new unique listings.")
            else:
                print("-> No active listings found.")
        except Exception as e:
            print(f"-> Warning for '{company}': {e}", file=sys.stderr)
            
        if idx < len(target_list) - 1:
            time.sleep(random.uniform(1.5, 3.5))
            
    print(f"\nTargeted company collection complete. Total new jobs stored: {total_new}")
    return total_new

def run_collector(limit_per_query=20, hours_old=168, include_companies=True):
    db.init_db()
    total_new_jobs = 0
    
    print(f"Starting job collection for the last {hours_old} hours...")
    
    # Use reliable India-compatible sources (linkedin & indeed; JobSpy naukri adapter returns 406 recaptcha)
    sites = ["linkedin", "indeed"]
    print(f"Using India-compatible sources: {', '.join(sites)}")
    
    search_terms = get_dynamic_search_terms()
    print(f"Loaded {len(search_terms)} dynamic search queries derived from your resume profile.")
    
    for index, term in enumerate(search_terms):
        print(f"\n[{index+1}/{len(search_terms)}] Searching for: '{term}' in India...")
        try:
            kwargs = {"hours_old": hours_old} if hours_old else {}
            jobs = scrape_jobs(
                site_name=sites,
                search_term=term,
                location="India",
                results_wanted=limit_per_query,
                country_indeed='india',
                **kwargs
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
                    country_indeed='india',
                    **kwargs
                )
                if not jobs.empty:
                    new_count = db.add_jobs(jobs)
                    total_new_jobs += new_count
                    print(f"-> [Fallback] Found {len(jobs)} jobs. Inserted {new_count} new unique jobs.")
            except Exception as fallback_err:
                print(f"-> [Fallback Error] Failed: {fallback_err}", file=sys.stderr)

        if index < len(search_terms) - 1:
            time.sleep(random.uniform(2.0, 4.0))

    # Run dedicated targeted company collection for elite tech employers in India
    if include_companies:
        company_jobs_count = run_company_collector(limit_per_company=10, hours_old=None)
        total_new_jobs += company_jobs_count

    # Run dedicated remote job collection
    remote_jobs_count = run_remote_collector(limit_per_query=limit_per_query, hours_old=hours_old)
    total_new_jobs += remote_jobs_count

    print(f"\nJob collection complete. Total new unique jobs stored: {total_new_jobs} (including {remote_jobs_count} remote)")
    return total_new_jobs


def run_remote_collector(limit_per_query=15, hours_old=72):
    """Dedicated scraper for remote and work-from-anywhere software opportunities."""
    db.init_db()
    total_remote = 0
    sites = ["indeed", "linkedin"]

    remote_queries = [
        "Applied AI Engineer",
        "AI Engineer",
        "Generative AI Engineer",
        "Machine Learning Engineer",
        "Software Development Engineer",
        "Software Engineer",
        "Backend Developer",
        "Python Developer",
        "Full Stack Developer",
        "Software Engineer Intern",
        "AI Intern",
    ]

    print(f"\n====================================================")
    print(f"🌐 INITIATING DEDICATED REMOTE JOB SCRAPER")
    print(f"====================================================")

    for idx, term in enumerate(remote_queries):
        print(f"\nSearching Remote: '{term}'...")
        try:
            jobs = scrape_jobs(
                site_name=sites,
                search_term=term,
                location="India",
                is_remote=True,
                results_wanted=limit_per_query,
                hours_old=hours_old,
                country_indeed='india'
            )
            if not jobs.empty:
                new_cnt = db.add_jobs(jobs)
                total_remote += new_cnt
                print(f"-> [Remote Scrape] Found {len(jobs)} candidates. Inserted {new_cnt} new listings.")
            else:
                print("-> No remote jobs found for this query.")
        except Exception as e:
            print(f"-> Remote query warning for '{term}': {e}", file=sys.stderr)

        if idx < len(remote_queries) - 1:
            time.sleep(random.uniform(2.0, 4.0))

    print(f"\nRemote collection complete. New remote jobs stored: {total_remote}")
    return total_remote


if __name__ == "__main__":
    limit = 20
    hours = 72
    if "--remote" in sys.argv:
        run_remote_collector(limit, hours)
    elif "--companies" in sys.argv:
        run_company_collector(limit_per_company=15, hours_old=hours)
    elif "--roles" in sys.argv:
        run_collector(limit, hours, include_companies=False)
    else:
        if len(sys.argv) > 1 and sys.argv[1].isdigit():
            limit = int(sys.argv[1])
        if len(sys.argv) > 2 and sys.argv[2].isdigit():
            hours = int(sys.argv[2])
        run_collector(limit, hours, include_companies=True)

