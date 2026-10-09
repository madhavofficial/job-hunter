import sys
import pandas as pd
from jobspy import scrape_jobs
import db
from quality import LINKEDIN_EASY_APPLY_SITE

import os
import re
import random
import time
from datetime import date

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

def get_dynamic_target_companies(limit: int = 40) -> list[str]:
    """Dynamically get verified employer names from registered ATS boards and product postings."""
    try:
        return db.get_dynamic_target_companies(limit=limit)
    except Exception:
        return []


class _DynamicTargetCompanies(list):
    """Dynamic company list that resolves verified employers dynamically without static lists in code."""
    def __contains__(self, item):
        raw = str(item or "").strip().lower()
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM ats_boards WHERE is_active = 1 AND lower(board_slug) = ?", (raw,))
        if cur.fetchone():
            conn.close()
            return True
        cur.execute("SELECT 1 FROM company_classifications WHERE company_normalized = ? AND category IN ('Big Tech & Global MNC', 'Unicorn / Tech Giant', 'AI & Tech Startup')", (raw,))
        if cur.fetchone():
            conn.close()
            return True
        cur.execute("SELECT 1 FROM jobs WHERE (site LIKE 'ats:%' OR score >= 75) AND lower(company) = ?", (raw,))
        found = cur.fetchone()
        conn.close()
        return bool(found)

    def __iter__(self):
        return iter(get_dynamic_target_companies(limit=50))

    def __len__(self):
        return len(get_dynamic_target_companies(limit=50))


TARGET_TECH_COMPANIES = _DynamicTargetCompanies()



# JobSpy's Glassdoor adapter cannot resolve the country-wide "India" location

# used by this pipeline, and its ZipRecruiter adapter only supports US/Canada.
# Keep the source list explicit so unsupported boards do not generate noisy,
# predictable failures on every query.
# JobSpy supports Naukri directly. Glassdoor and Monster are intentionally not
# listed here: this installed JobSpy release has no reliable India Monster
# adapter, and Glassdoor currently returns 400s for this pipeline's query shape.
SUPPORTED_INDIA_SITES = ("indeed", "linkedin", "naukri")

# Unauthenticated LinkedIn guest search starts returning HTTP 429 after about
# 10-15 queries. Each query is one page when results_wanted stays at 10; a
# larger page size costs another request. The daily pass stays under that.
EASY_APPLY_QUERY_BUDGET = 8
EASY_APPLY_PAGE_SIZE = 10


def linkedin_easy_apply_rows(jobs: pd.DataFrame) -> pd.DataFrame:
    """Keep scraped LinkedIn rows and mark them as Easy Apply.

    The caller must already have searched with LinkedIn's Easy Apply filter.
    Indeed and other boards in the same frame are dropped.
    """
    if jobs is None or jobs.empty or "site" not in jobs.columns:
        return jobs.iloc[0:0] if isinstance(jobs, pd.DataFrame) else pd.DataFrame()
    kept = jobs[jobs["site"].astype(str).str.lower().eq("linkedin")].copy()
    kept["site"] = LINKEDIN_EASY_APPLY_SITE
    return kept


def scrape_listings(easy_apply: bool = False, **kwargs) -> pd.DataFrame:
    """Scrape one query. Easy Apply mode asks LinkedIn for f_AL jobs only."""
    if easy_apply:
        kwargs["site_name"] = ["linkedin"]
        kwargs["easy_apply"] = True
    jobs = scrape_jobs(**kwargs)
    if easy_apply:
        jobs = linkedin_easy_apply_rows(jobs)
    return jobs


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

    # Generate targeted combinations (direct title, intern, associate)
    for tech in core_techs:
        terms.add(tech)
        terms.add(f"{tech} Intern")
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
    ])

    return sorted(list(terms))


def easy_apply_queries(day_index: int | None = None) -> list[tuple[str, bool]]:
    """Return at most EASY_APPLY_QUERY_BUDGET (term, is_remote) searches.

    The pool is the resume role list plus a few remote titles. Each run takes
    a rotating slice so the week covers the pool without 70 searches in a day.
    """
    remote_terms = (
        "Software Engineer",
        "AI Engineer",
        "Software Engineer Intern",
    )
    pool: list[tuple[str, bool]] = []
    seen = set()
    for term, is_remote in [(term, False) for term in get_dynamic_search_terms()] + [
        (term, True) for term in remote_terms
    ]:
        key = (term.lower(), is_remote)
        if key in seen:
            continue
        seen.add(key)
        pool.append((term, is_remote))
    if not pool:
        return []
    if day_index is None:
        day_index = date.today().toordinal()
    start = day_index % len(pool)
    rotated = pool[start:] + pool[:start]
    return rotated[:EASY_APPLY_QUERY_BUDGET]


def run_easy_apply_collector(limit_per_query: int = 20, hours_old: int = 168) -> int:
    """Collect a small LinkedIn Easy Apply slice. Does not walk companies or every remote title."""
    db.init_db()
    queries = easy_apply_queries()
    page_size = min(limit_per_query, EASY_APPLY_PAGE_SIZE)
    print(
        f"LinkedIn Easy Apply: {len(queries)} searches, {page_size} results each "
        f"(budget {EASY_APPLY_QUERY_BUDGET}, one page per search).",
        flush=True,
    )
    total_new = 0
    for index, (term, is_remote) in enumerate(queries):
        label = "Remote" if is_remote else "India"
        print(f"\n[{index + 1}/{len(queries)}] Easy Apply {label}: '{term}'...", flush=True)
        try:
            jobs = scrape_listings(
                easy_apply=True,
                site_name=["linkedin"],
                search_term=term,
                location="India",
                is_remote=is_remote,
                results_wanted=page_size,
                hours_old=hours_old,
                country_indeed="india",
            )
            if not jobs.empty:
                added = db.add_jobs(jobs)
                total_new += added
                print(f"-> Found {len(jobs)} Easy Apply jobs. Inserted {added} new listings.", flush=True)
            else:
                print("-> No Easy Apply jobs for this query.", flush=True)
        except Exception as exc:
            print(f"-> Easy Apply query failed for '{term}': {exc}", file=sys.stderr)
        if index < len(queries) - 1:
            time.sleep(random.uniform(2.0, 4.0))
    print(f"\nEasy Apply collection complete. New jobs stored: {total_new}", flush=True)
    return total_new


def run_company_collector(companies=None, limit_per_company=15, hours_old=None, location="India", easy_apply: bool = False):
    """Targeted collector for tier-1 tech giants, decacorns, and unicorns.
    
    Directly scrapes target company openings on LinkedIn and Indeed in India,
    guaranteeing that top-tier postings (e.g. OpenAI, Anthropic, Google, Uber, Razorpay)
    are discovered immediately rather than hoping generic queries rank them.
    """
    db.init_db()
    total_new = 0
    target_list = companies or get_dynamic_target_companies(limit=30)
    enable_indeed = os.getenv("ENABLE_INDEED_SCRAPER", "false").lower() in ("true", "1", "yes")
    sites = ["linkedin"] if easy_apply else (["linkedin", "indeed"] if enable_indeed else ["linkedin"])
    
    print(f"\n====================================================")
    print(f"🎯 INITIATING TARGETED TIER-1 COMPANY SCRAPER")
    print(f"Targeting {len(target_list)} dynamic tech companies in {location}")
    print(f"Sources: {', '.join(sites)} (Indeed spam filter: {'DISABLED' if enable_indeed else 'ACTIVE'})")
    if easy_apply:
        print("LinkedIn filter: Easy Apply only")
    print(f"====================================================")
    
    for idx, company in enumerate(target_list):
        print(f"\n[{idx+1}/{len(target_list)}] Searching company: '{company}' in {location}...")
        try:
            kwargs = {"hours_old": hours_old} if hours_old else {}
            jobs = scrape_listings(
                easy_apply=easy_apply,
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

def run_collector(limit_per_query=20, hours_old=168, include_companies=True, easy_apply: bool = False):
    if easy_apply:
        return run_easy_apply_collector(limit_per_query, hours_old)
    db.init_db()
    total_new_jobs = 0
    
    print(f"Starting job collection for the last {hours_old} hours...")
    
    enable_indeed = os.getenv("ENABLE_INDEED_SCRAPER", "false").lower() in ("true", "1", "yes")
    sites = ["linkedin"] if easy_apply else (["linkedin", "indeed"] if enable_indeed else ["linkedin"])
    print(f"Using high-signal sources: {', '.join(sites)} (Indeed spam filter: {'DISABLED' if enable_indeed else 'ACTIVE'})")
    if easy_apply:
        print("LinkedIn filter: Easy Apply only. Other LinkedIn listings are not stored.")

    
    search_terms = get_dynamic_search_terms()
    print(f"Loaded {len(search_terms)} dynamic search queries derived from your resume profile.")
    
    for index, term in enumerate(search_terms):
        print(f"\n[{index+1}/{len(search_terms)}] Searching for: '{term}' in India...")
        try:
            kwargs = {"hours_old": hours_old} if hours_old else {}
            jobs = scrape_listings(
                easy_apply=easy_apply,
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
            if enable_indeed and not easy_apply:
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
        company_jobs_count = run_company_collector(limit_per_company=10, hours_old=None, easy_apply=easy_apply)
        total_new_jobs += company_jobs_count

    # Run dedicated remote job collection
    remote_jobs_count = run_remote_collector(limit_per_query=limit_per_query, hours_old=hours_old, easy_apply=easy_apply)
    total_new_jobs += remote_jobs_count

    print(f"\nJob collection complete. Total new unique jobs stored: {total_new_jobs} (including {remote_jobs_count} remote)")
    return total_new_jobs


def run_remote_collector(limit_per_query=15, hours_old=72, easy_apply: bool = False):
    """Dedicated scraper for remote and work-from-anywhere software opportunities."""
    db.init_db()
    total_remote = 0
    enable_indeed = os.getenv("ENABLE_INDEED_SCRAPER", "false").lower() in ("true", "1", "yes")
    sites = ["linkedin"] if easy_apply else (["linkedin", "indeed"] if enable_indeed else ["linkedin"])


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
    if easy_apply:
        print("LinkedIn filter: Easy Apply only")
    print(f"====================================================")

    for idx, term in enumerate(remote_queries):
        print(f"\nSearching Remote: '{term}'...")
        try:
            jobs = scrape_listings(
                easy_apply=easy_apply,
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
    easy_apply = "--easy-apply" in sys.argv
    numbers = [int(arg) for arg in sys.argv[1:] if arg.isdigit()]
    limit = numbers[0] if numbers else 20
    hours = numbers[1] if len(numbers) > 1 else 72
    if easy_apply:
        run_easy_apply_collector(limit, hours)
    elif "--remote" in sys.argv:
        run_remote_collector(limit, hours, easy_apply=easy_apply)
    elif "--companies" in sys.argv:
        run_company_collector(limit_per_company=15, hours_old=hours, easy_apply=easy_apply)
    elif "--roles" in sys.argv:
        run_collector(limit, hours, include_companies=False, easy_apply=easy_apply)
    else:
        run_collector(limit, hours, include_companies=True, easy_apply=easy_apply)

