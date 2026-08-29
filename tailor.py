import os
import sys
from groq import Groq
import db
import config
from pdf_utils import markdown_to_pdf
import github_portfolio

def tailor_materials(job_id: str):
    db.init_db()
    
    # Load resume
    resume_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resume.md")
    if not os.path.exists(resume_path):
        print(f"Error: resume.md not found.", file=sys.stderr)
        return None
        
    with open(resume_path, "r", encoding="utf-8") as f:
        resume_text = f.read()

    # Auto-ingest if job_id is a URL
    if job_id.startswith("http://") or job_id.startswith("https://"):
        import custom_job
        resolved_id = custom_job.ingest_custom_job(job_id)
        if not resolved_id:
            return None
        job_id = resolved_id

    # Fetch GitHub portfolio
    print("-> Fetching candidate's GitHub portfolio for dynamic project alignment...")
    portfolio = github_portfolio.fetch_github_portfolio()
    portfolio_text = github_portfolio.format_github_portfolio_for_prompt(portfolio)
        
    # Get job details
    conn = db.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
    job = cursor.fetchone()
    conn.close()
    
    if not job:
        print(f"Error: Job ID {job_id} not found in database.", file=sys.stderr)
        return None
        
    title = job['title']
    company = job['company']
    description = job['description'] or ""
    
    print(f"Tailoring application materials for: '{title}' at '{company}'...")
    
    # Init Groq
    from dotenv import load_dotenv
    load_dotenv()
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("Error: GROQ_API_KEY not found.", file=sys.stderr)
        return None
        
    client = Groq(api_key=api_key)
    model_name = config.get_best_model(client)
    print(f"Using Groq model: {model_name}")
    
    # Create tailored directory
    tailored_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tailored")
    os.makedirs(tailored_dir, exist_ok=True)
    
    # Tailor Resume Prompt
    resume_prompt = f"""You are an expert resume optimizer and technical hiring specialist. Your task is to adapt the candidate's resume for a specific job posting.

Instructions & Rules:
1. PROFESSIONAL EXPERIENCE: Preserve all professional internships (Qualcomm, O.C. Tanner) with all hard metrics (8,700 tickets, 15+ skills, 50+ tickets, 70% coverage), technical depth, and guardrails. Do not compress or delete these experiences.
2. DYNAMIC PROJECT REPLACEMENT & ALIGNMENT:
   - Carefully review the Job Posting requirements (required languages, frameworks, domain, e.g. DevOps, TypeScript, Full-Stack Web, Backend, Distributed Systems, AI/ML, Data Science, Databases).
   - Compare the candidate's Current Resume Projects with the candidate's Verified GitHub Project Portfolio.
   - Select the 3 to 4 BEST-FITTING projects from the combined pool of projects (Current Resume + GitHub Portfolio).
   - REPLACE less relevant projects on the base resume with stronger-matching GitHub projects where appropriate:
     * For DevOps / Cloud / Automation / Tooling roles -> prioritize 'job-hunter'.
     * For Full-Stack / TypeScript / FinTech / Database roles -> prioritize 'Ultimate-Trader-Dashboard' or 'University-DBMS-Management-'.
     * For AI / RAG / Agent / NLP roles -> prioritize 'evidence-grounded-clinical-literature-synthesis', 'CareerTime', or 'neuro_capstone'.
     * For Computer Vision / Deep Learning -> prioritize 'Sketch Recognition System'.
     * For Data Science / Regression / Analytics -> prioritize 'Forecasting-Bike-Rental-Demand'.
   - FIRST BULLET EXPLAINS WHAT THE PROJECT DOES: For EVERY project on the resume, the FIRST bullet point MUST clearly state WHAT the project is and WHAT it does (its core product capability, user function, and problem solved). The remaining bullets should then detail the deep engineering architecture, database design, concurrency models, performance optimizations, and quantitative metrics.
   - For each selected project, write 3 to 4 detailed, highly technical bullet points demonstrating real engineering architecture, libraries, and design patterns from its verified documentation.
3. SKILLS SECTION: Update the Technical Skills section to highlight the exact languages and tools used across the selected projects and experience (e.g., add TypeScript, Docker, Prisma, etc. if featuring TypeScript/Full-Stack projects).
4. ZERO FABRICATION: Do NOT invent non-existent projects, companies, durations, graduation date (May 2027), or credentials. Rely strictly on facts in the candidate's resume and GitHub portfolio. Do NOT include GPA on the resume.
5. FORMATTING & TYPOGRAPHY:
   - Heavily utilize markdown bolding (**bold**) for all key metrics, numbers, core technologies, and frameworks across every bullet point (e.g. **8,700** tickets, **70%** coverage, **40%** latency reduction, **TypeScript**, **PostgreSQL**, **Prisma ORM**, **Docker**).
   - Format project titles as: `### Project Name (Core Technologies)` followed immediately by `*GitHub: <url>*`.
   - Output the COMPLETE tailored resume in clean, professional Markdown.

Candidate Base Resume:
{resume_text}

Candidate's Verified GitHub Project Portfolio:
{portfolio_text}

Job Posting:
Company: {company}
Title: {title}
Description:
{description[:3500]}

Please output the COMPLETE tailored resume in Markdown.
"""

    try:
        # Generate Resume
        tailored_resume = None
        candidate_models = [model_name] + [m for m in config.get_fallback_models() if m != model_name]
        
        print("-> Generating tailored resume with deep project alignment...")
        for active_model in candidate_models:
            retries = 0
            max_retries = max(1, config.key_manager.get_num_keys())
            while retries < max_retries:
                try:
                    res_response = client.chat.completions.create(
                        model=active_model,
                        messages=[{"role": "user", "content": resume_prompt}],
                        temperature=0.2
                    )
                    tailored_resume = res_response.choices[0].message.content
                    break
                except Exception as e:
                    err_str = str(e).lower()
                    if any(term in err_str for term in ["rate_limit", "429", "limit_exceeded", "tokens per day"]):
                        print(f"Rate limit hit on {active_model} during resume tailoring: {e}")
                        retries += 1
                        if retries < max_retries:
                            client = config.cycle_groq_client()
                            continue
                        else:
                            print(f"-> All keys exhausted for {active_model}. Falling back to next model...")
                            break
                    raise e
            if tailored_resume:
                break
                
        if not tailored_resume:
            raise ValueError("Failed to generate tailored resume after trying all keys and fallback models.")
        
        # Save files
        clean_company = "".join([c for c in company if c.isalnum() or c in (' ', '_')]).replace(' ', '_')
        clean_title = "".join([c for c in title if c.isalnum() or c in (' ', '_')]).replace(' ', '_')
        
        resume_filename = f"{clean_company}_{clean_title}_Resume.md"
        resume_filepath = os.path.join(tailored_dir, resume_filename)
        resume_pdf_filepath = os.path.join(tailored_dir, f"{clean_company}_{clean_title}_Resume.pdf")
        
        with open(resume_filepath, "w", encoding="utf-8") as f:
            f.write(tailored_resume)
            
        markdown_to_pdf(tailored_resume, resume_pdf_filepath)
            
        print(f"-> Tailored Resume saved to: {resume_filepath}")
        print(f"-> ATS Resume PDF saved to: {resume_pdf_filepath}")
        
        # Store generated materials in database
        db.store_tailored_materials(job_id, resume_filepath, None, resume_pdf_filepath, None)
        
        return resume_filepath, resume_pdf_filepath
        
    except Exception as e:
        print(f"Error generating tailored materials: {e}", file=sys.stderr)
        return None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tailor.py [job_id]", file=sys.stderr)
        sys.exit(1)
    tailor_materials(sys.argv[1])
