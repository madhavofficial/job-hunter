import os
import json
import time
import sys
from groq import Groq
import db
import config
from screening import classify_company_tier, deterministic_hard_filter

def load_resume():
    resume_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resume.md")
    if not os.path.exists(resume_path):
        print(f"Error: resume.md not found at {resume_path}", file=sys.stderr)
        return ""
    with open(resume_path, "r", encoding="utf-8") as f:
        return f.read()

def fetch_description_from_web(url, site):
    if not url:
        return None
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        if "linkedin.com" in url:
            import re
            import requests
            from bs4 import BeautifulSoup
            
            # Clean URL to standard view format: /jobs/view/ID
            match = re.search(r"/jobs/view/(\d+)", url)
            if match:
                url = f"https://www.linkedin.com/jobs/view/{match.group(1)}"
            
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code in {401, 403, 429} or any(marker in res.text.lower() for marker in ("authwall", "captcha", "challenge")):
                print(f"Warning: LinkedIn description unavailable ({res.status_code}); continuing without it.", file=sys.stderr)
                return None
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, 'html.parser')
                desc_div = soup.find(class_="show-more-less-html__markup")
                if not desc_div:
                    desc_div = soup.find(class_="description__text")
                if desc_div:
                    return desc_div.get_text(separator="\n").strip()
                # If description container is missing but page loaded, check for closed/recommendation signs
                page_text = soup.get_text().lower()
                if "show more jobs like this" in page_text or "similar jobs" in page_text or "no longer accepting applications" in page_text:
                    return "EXPIRED_OR_CLOSED"
    except Exception as e:
        print(f"Warning: Failed to fetch description from {url}: {e}", file=sys.stderr)
    return None

def run_matcher():
    db.init_db()
    
    # Load resume
    resume_text = load_resume()
    if not resume_text:
        return
        
    # Get unprocessed jobs
    unprocessed = db.get_unprocessed_jobs()
    if not unprocessed:
        print("No new unprocessed jobs found.")
        return
        
    print(f"Found {len(unprocessed)} unprocessed jobs. Applying deterministic safeguards...")

    eligible = []
    prefiltered_count = 0
    for job in unprocessed:
        passes, reason = deterministic_hard_filter(job)
        if passes:
            eligible.append(job)
            continue
        db.update_job_match(job['job_id'], 0, "rejected", "", f"REJECTED: {reason}")
        prefiltered_count += 1

    if not eligible:
        print(f"Deterministic safeguards rejected {prefiltered_count} jobs; no LLM matching required.")
        return
    unprocessed = eligible
    print(f"Deterministic safeguards rejected {prefiltered_count}; sending {len(unprocessed)} jobs to the LLM.")
    print("Initializing Groq client...")
    
    # Init Groq client
    # Groq API key is loaded from .env automatically if python-dotenv is used or we can load it manually
    from dotenv import load_dotenv
    load_dotenv()
    
    try:
        client = config.get_groq_client()
        model_name = config.get_best_model(client)
        print(f"Using Groq model: {model_name}")
    except Exception as e:
        print(f"Error initializing Groq client: {e}", file=sys.stderr)
        return
    
    # Define prompt instructions
    system_prompt = """You are an AI recruiter screening job applications for a Computer Science & Engineering (CSE) candidate.
Your task is to evaluate the provided job posting against the candidate's profile and resume.

Candidate Profile:
- Name: Madhav Jayam
- Education: CSE student at PES University, Bengaluru.
- Expected Graduation: May 2027.
- Work Experience: Software Engineering Intern at Qualcomm (May-Jul 2026), Software Engineering Intern at O.C. Tanner (Jun-Jul 2025).
- Stack: Python, Java, Scala, C, JavaScript, React, Node.js, Express, Streamlit, PyTorch, LangChain, Android (Kotlin/Espresso), SQL/NoSQL.
- Target: Full Software Engineering scope — Strong interest across Core Software Engineering (Backend systems, Distributed architecture, API services, Data platforms) AND Artificial Intelligence (AI/ML, RAG, LLM Agentic workflows).

You MUST apply the following evaluation layers:

LAYER 1: HARD FILTERS (If any fails, reject immediately)
1. Batch/Graduation Year: Candidate graduates in May 2027. If the job explicitly requires graduating in 2025/2026 and states 2027 graduates are not eligible, set passes_hard_filters to false. Otherwise (open, unspecified, or accepts 2027), set to true.
2. Experience Level: The candidate has intern-level experience. If the job explicitly requires senior-level professional experience (e.g., 3+ years, 5+ years, Lead, Manager), set passes_hard_filters to false. Internship, co-op, entry-level, junior, or 0-2 years roles pass.
3. Location: Must be in India (any city, e.g., Bengaluru, Pune, Hyderabad, Gurgaon, Mumbai) or Remote. If it explicitly requires relocation outside India, set passes_hard_filters to false.
4. Role Type: Must be a CSE-related role. Reject non-CSE roles (e.g., Sales, Marketing, Mechanical/Civil Engineer, HR).
5. Legitimacy / Company Spam Filter: Reject anonymous posters ("None", "Confidential", "Private Limited"), resume-harvesting consultancies, or unpaid training institutes. Real tech startups, funded ventures, and established enterprises pass.

LAYER 2: COMPANY TIER CLASSIFICATION
Classify the company into one of the following tiers:
- "Tier 1: Product Company / Tech Startup": Legitimate engineering product companies, funded tech startups, and developer platforms (e.g., JuiceLabs, Nextburb, WisdomAI, gnani.ai, Stripe, OpenAI, Swiggy, Zerodha, Postman, Razorpay, high-tech AI/software labs).
- "Tier 2: Enterprise / Tech Services": Established global tech enterprises, MNCs, and reputable IT/engineering services (e.g., Qualcomm, Novartis, Munich Re, Infosys, DHL, UST, Indium, Cisco, Intel).
- "Tier 3: Staffing Agency / General Consultancy": Third-party recruitment agencies, staffing firms, or generic consultancies.

LAYER 3: COMPATIBILITY SCORING (Only for those passing hard filters)
- Calculate a score between 0 and 100 representing how well the job matches the candidate's skills and career goals.
- Strong Matches (85-98%):
  * Core Software Engineer / Developer roles (Backend, Distributed Systems, Python/Java/C/Scala infrastructure, API development, Systems engineering).
  * AI/ML, NLP, RAG, GenAI, LLM Agents, and Data Engineering roles.
- Baseline Matches (80-84%):
  * General Full-Stack Developer roles (React/Node.js) or Developer Productivity / QA Automation roles.
- Low Priority Matches (75-79%):
  * Pure Frontend-only (CSS/HTML UI tweaking) or standalone mobile maintenance.

RESPONSE FORMAT:
You MUST respond with a JSON object. Use the following structure:
{
  "passes_hard_filters": true/false,
  "rejection_reason": "Brief explanation of why it failed hard filters, or null if it passed",
  "company_tier": "Tier 1: Product Company / AI Startup" | "Tier 2: Enterprise / Tech Services" | "Tier 3: Staffing Agency / General Consultancy",
  "compatibility_score": 85, // Integer 0-100. Set to 0 if passes_hard_filters is false.
  "evidence": [
    "Quote from description confirming graduation year/experience/location",
    "Quote confirming skills/duration"
  ],
  "matching_notes": "A brief user-friendly paragraph summarizing why this job is a match (or why it was rejected)."
}
"""

    processed_count = 0
    shortlisted_count = 0
    
    for job in unprocessed:
        job_id = job['job_id']
        title = job['title']
        company = job['company']
        location = job['location']
        description = job['description'] or ""
        job_url = job['job_url']
        site = job['site']
        
        # Fetch description if empty
        if not description:
            print(f"Description empty for '{title}' at '{company}'. Fetching from web...")
            fetched_desc = fetch_description_from_web(job_url, site)
            if fetched_desc == "EXPIRED_OR_CLOSED":
                print(f"-> REJECTED: Listing closed / expired on {site.upper()}.")
                db.update_job_match(
                    job_id=job_id,
                    score=0,
                    status="rejected",
                    evidence="",
                    matching_notes=f"REJECTED: Listing is closed / no longer accepting applications on {site.upper()}."
                )
                continue
            elif fetched_desc:
                description = fetched_desc
                # Update in DB
                conn = db.get_db_connection()
                cursor = conn.cursor()
                cursor.execute("UPDATE jobs SET description = ? WHERE job_id = ?", (description, job_id))
                conn.commit()
                conn.close()
                print(f"-> Successfully fetched and saved description ({len(description)} chars)")
            else:
                print("-> Could not fetch description. Proceeding with title-only matching.")
        
        print(f"\nProcessing: '{title}' at '{company}' ({location})...")
        
        user_prompt = f"""Evaluate this job:
Title: {title}
Company: {company}
Location: {location}
Job Type: {job['job_type'] or 'Unspecified'}
Experience Range: {job['experience_range'] or 'Unspecified'}

Description:
{description[:6000]} # Truncate description if extremely long to fit context
"""

        try:
            response = None
            candidate_models = [model_name] + [m for m in config.get_fallback_models() if m != model_name]
            
            for active_model in candidate_models:
                retries = 0
                max_retries = max(1, config.key_manager.get_num_keys())

                while retries < max_retries:
                    try:
                        response = client.chat.completions.create(
                            model=active_model,
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt}
                            ],
                            temperature=0.0,
                            response_format={"type": "json_object"}
                        )
                        break
                    except Exception as e:
                        err_str = str(e).lower()
                        if any(term in err_str for term in ["rate_limit", "429", "limit_exceeded", "tokens per day"]):
                            print(f"Rate limit hit on {active_model}: {e}")
                            retries += 1
                            if retries < max_retries:
                                client = config.cycle_groq_client()
                                continue
                            else:
                                print(f"-> All keys exhausted for {active_model}. Falling back to next model...")
                                break
                        raise e
                if response is not None:
                    break
                    
            if response is None:
                raise ValueError("Failed to get response after cycling through all keys and fallback models.")
            
            result_json = response.choices[0].message.content
            result = json.loads(result_json)
            
            passes = result.get("passes_hard_filters", False)
            try:
                score = max(0, min(100, int(result.get("compatibility_score", 0))))
            except (TypeError, ValueError):
                score = 0
            rejection_reason = result.get("rejection_reason", "")
            company_tier = classify_company_tier(company)
            evidence = result.get("evidence", [])
            notes = result.get("matching_notes", "")
            
            # If identified as an unverified/staffing agency or anonymous poster, reject immediately
            if company_tier.startswith("Tier 3"):
                passes = False
                rejection_reason = rejection_reason or "Identified as recruitment/staffing agency or unverified training consultancy."
            
            # Format evidence list as a string
            evidence_str = "\n".join([f"- {ev}" for ev in evidence])
            
            # Determine status
            # If passes hard filters and score >= 75, we shortlist it. Otherwise rejected.
            if passes and score >= 75:
                status = "shortlisted"
                shortlisted_count += 1
                print(f"-> SHORTLISTED ({company_tier}): Score={score}%")
            else:
                status = "rejected"
                score = 0
                if rejection_reason:
                    notes = f"REJECTED: {rejection_reason}\n\n{notes}"
                print(f"-> REJECTED: {rejection_reason or 'Low compatibility score'}")
                
            db.update_job_match(
                job_id=job_id,
                score=score,
                status=status,
                evidence=evidence_str,
                matching_notes=notes
            )
            
            processed_count += 1
            
            # Brief sleep to avoid hitting rate limits too fast
            time.sleep(1.0)
            
        except Exception as e:
            print(f"Error processing job {job_id}: {e}", file=sys.stderr)
            # Sleep longer on error (possibly rate limit)
            time.sleep(5.0)
            
    print(f"\nMatching complete. Processed {processed_count} jobs. Shortlisted {shortlisted_count} jobs.")

if __name__ == "__main__":
    run_matcher()
