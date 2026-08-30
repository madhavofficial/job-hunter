"""Custom Job Ingestion and Tailoring Pipeline for Job Hunter.

Allows users to pass any custom job URL (LinkedIn, Greenhouse, Lever, Ashby,
Workday, Indeed, or any arbitrary company careers page) to automatically:
1. Fetch and parse job title, company, location, and full description.
2. Store the listing in jobs.db with full compatibility scoring.
3. Generate tailored single-page ATS Resume (PDF & Markdown) aligned with candidate GitHub portfolio.
4. Launch the application workflow with direct browser open.
"""

import hashlib
import json
import re
import sys
import urllib.parse
from typing import Dict, Optional, Tuple

import bs4
import requests
from groq import Groq

import config
import db
import matcher
import tailor


USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]


def extract_linkedin_id(url: str) -> Optional[str]:
    """Extract numeric job ID from a LinkedIn URL."""
    if "linkedin.com" not in url:
        return None
    match = re.search(r"/jobs/view/(\d+)", url) or re.search(r"currentJobId=(\d+)", url)
    return match.group(1) if match else None


def fetch_webpage_content(url: str) -> Tuple[str, str]:
    """Fetch webpage HTML and return (page_title, clean_text_content)."""
    headers = {
        "User-Agent": USER_AGENTS[0],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    # Handle LinkedIn guest API if applicable
    lid = extract_linkedin_id(url)
    if lid and "linkedin.com" in url:
        guest_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{lid}"
        try:
            resp = requests.get(guest_url, headers=headers, timeout=12)
            if resp.status_code == 200:
                soup = bs4.BeautifulSoup(resp.text, "html.parser")
                title_elem = soup.find("h2", class_="top-card-layout__title") or soup.find("h1")
                comp_elem = soup.find("a", class_="topcard__org-name-link") or soup.find("span", class_="topcard__flavor")
                desc_elem = soup.find("div", class_="show-more-less-html__markup") or soup.find("div", class_="description__text")

                title = title_elem.get_text(strip=True) if title_elem else ""
                company = comp_elem.get_text(strip=True) if comp_elem else ""
                desc = desc_elem.get_text(separator="\n", strip=True) if desc_elem else soup.get_text(separator="\n", strip=True)
                if desc:
                    return f"{title} at {company}", f"Title: {title}\nCompany: {company}\n\nDescription:\n{desc}"
        except Exception as e:
            print(f"LinkedIn guest scrape notice: {e}. Falling back to standard fetch...", file=sys.stderr)

    # Standard Webpage Fetch
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()

    soup = bs4.BeautifulSoup(resp.text, "html.parser")

    # Remove irrelevant tags
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "svg", "button", "iframe"]):
        tag.decompose()

    page_title = soup.title.string.strip() if soup.title and soup.title.string else "Job Opportunity"
    clean_text = soup.get_text(separator="\n", strip=True)

    # Compress whitespace
    lines = [line.strip() for line in clean_text.splitlines() if len(line.strip()) > 1]
    compact_text = "\n".join(lines[:350])  # limit to ~350 lines

    return page_title, compact_text


def parse_job_with_llm(url: str, raw_text: str, page_title: str) -> Dict[str, str]:
    """Use Groq LLM to extract structured fields from raw job page text."""
    prompt = f"""You are a specialized job data extractor. Extract the structured job listing information from the provided webpage text.

Webpage Title: {page_title}
URL: {url}

Webpage Content:
{raw_text[:6000]}

Respond ONLY with a valid JSON object matching this exact schema:
{{
  "title": "<Exact Job Title, e.g. Senior Software Engineer - Backend>",
  "company": "<Exact Company Name, e.g. Google or Datadog>",
  "location": "<Job Location / Remote Status, e.g. Bengaluru, Karnataka, India or Remote>",
  "job_type": "<e.g. Full-time, Internship, Contract>",
  "skills": "<Comma-separated list of top required technologies and skills>",
  "description": "<Comprehensive job description including responsibilities and requirements (clean text, 3-6 paragraphs)>"
}}
"""

    client = config.cycle_groq_client()
    model_name = config.get_best_model(client)
    candidate_models = [model_name] + [m for m in config.get_fallback_models() if m != model_name]

    for model in candidate_models:
        for _ in range(max(1, config.key_manager.get_num_keys())):
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    response_format={"type": "json_object"},
                )
                content = response.choices[0].message.content
                data = json.loads(content)
                if data.get("title") and data.get("company"):
                    return data
            except Exception as e:
                err_str = str(e).lower()
                if any(term in err_str for term in ["rate_limit", "429", "limit_exceeded"]):
                    client = config.cycle_groq_client()
                    continue
                print(f"Notice: Parsing error on {model}: {e}", file=sys.stderr)
                break

    # Fallback heuristic if LLM unavailable
    return {
        "title": page_title[:60],
        "company": "Custom Opportunity",
        "location": "India / Remote",
        "job_type": "Full-time",
        "skills": "Software Engineering, Python, Backend",
        "description": raw_text[:3000],
    }


def ingest_custom_job(url: str, custom_text: Optional[str] = None) -> Optional[str]:
    """Ingests a custom job URL into jobs.db and returns its job_id."""
    db.init_db()

    print(f"\n====================================================")
    print(f"📥 INGESTING CUSTOM JOB OPPORTUNITY")
    print(f"Target URL: {url}")
    print(f"====================================================")

    # 1. Check if already in DB
    conn = db.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT job_id, title, company FROM jobs WHERE job_url = ? OR job_url_direct = ?", (url, url))
    existing = cursor.fetchone()
    conn.close()

    lid = extract_linkedin_id(url)
    if not existing and lid:
        conn = db.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT job_id, title, company FROM jobs WHERE job_id = ?", (f"li-{lid}",))
        existing = cursor.fetchone()
        conn.close()

    if existing:
        print(f"✓ Found existing job in database: `{existing['job_id']}` ({existing['title']} at {existing['company']})")
        return existing["job_id"]

    # 2. Fetch content
    try:
        if custom_text:
            page_title = "Custom Pasted Job"
            raw_text = custom_text
        else:
            print("Step 1/3: Scraping job description from URL...")
            page_title, raw_text = fetch_webpage_content(url)
    except Exception as e:
        print(f"Warning: Failed to fetch webpage directly ({e}).", file=sys.stderr)
        if not custom_text:
            print("\nPlease paste the job description text below (press Ctrl+D or Enter twice when done):")
            lines = []
            try:
                while True:
                    line = input()
                    lines.append(line)
            except EOFError:
                pass
            raw_text = "\n".join(lines).strip()
            page_title = "User Pasted Job"

    # 3. Parse with LLM
    print("Step 2/3: Analyzing role requirements & tech stack with AI...")
    parsed = parse_job_with_llm(url, raw_text, page_title)

    title = parsed.get("title", "Software Engineer").strip()
    company = parsed.get("company", "Custom Company").strip()
    location = parsed.get("location", "India / Remote").strip()
    description = parsed.get("description", raw_text).strip()
    skills = parsed.get("skills", "").strip()
    job_type = parsed.get("job_type", "Full-time").strip()

    # Generate deterministic ID
    if lid:
        job_id = f"li-{lid}"
        site = "linkedin"
    else:
        url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()[:10]
        job_id = f"custom-{url_hash}"
        site = "custom"

    print(f"-> Parsed: '{title}' at '{company}' ({location})")

    # 4. Insert into jobs.db
    conn = db.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT OR REPLACE INTO jobs (
        job_id, site, job_url, job_url_direct, title, company, location,
        date_posted, job_type, description, is_remote, skills, experience_range,
        score, status, matching_notes, evidence, created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, ?, 0, ?, '', ?, ?, ?, '', datetime('now'))
    """, (job_id, site, url, url, title, company, location, job_type, description, skills,
           90, "shortlisted", "Custom Ingested Opportunity"))
    conn.commit()
    conn.close()

    # 5. Evaluate match score
    print("Step 3/3: Evaluating compatibility with candidate resume...")
    try:
        resume_text = matcher.load_resume()
        client = config.cycle_groq_client()
        model_name = config.get_best_model(client)
        eval_prompt = f"""You are an expert technical hiring filter. Evaluate candidate fit for this job listing.

Candidate Resume:
{resume_text}

Job Posting:
Title: {title}
Company: {company}
Location: {location}
Description:
{description[:3500]}

Respond ONLY with a JSON object:
{{
  "compatibility_score": 92,
  "matching_notes": "1-2 sentences summarizing alignment with candidate skills and GitHub portfolio.",
  "evidence": ["Evidence 1", "Evidence 2"]
}}
"""
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": eval_prompt}],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        res_data = json.loads(response.choices[0].message.content)
        score = int(res_data.get("compatibility_score", 90))
        notes = res_data.get("matching_notes", "Custom Ingested Opportunity")
        evidence_list = res_data.get("evidence", [])
        evidence_str = "\n".join(f"- {e}" for e in evidence_list) if isinstance(evidence_list, list) else str(evidence_list)

        conn = db.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
        UPDATE jobs
        SET score = ?, matching_notes = ?, evidence = ?
        WHERE job_id = ?
        """, (score, notes, evidence_str, job_id))
        conn.commit()
        conn.close()
        print(f"-> Compatibility Score: {score}%")
    except Exception as e:
        print(f"Notice: Matcher evaluation defaulted ({e}).", file=sys.stderr)

    print(f"✅ Ingestion complete! Job ID: `{job_id}`\n")
    return job_id


def process_custom_url(url: str):
    """Full workflow: Ingests custom URL and executes 1-click tailored application."""
    job_id = ingest_custom_job(url)
    if not job_id:
        print("Error: Could not process job URL.", file=sys.stderr)
        return False

    import apply
    return apply.apply_single_job(job_id)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python custom_job.py <URL>")
        sys.exit(1)

    target_url = sys.argv[1].strip()
    process_custom_url(target_url)
