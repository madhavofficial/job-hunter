import os
import sys
from groq import Groq
import db
import config

def tailor_materials(job_id: str):
    db.init_db()
    
    # Load resume
    resume_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resume.md")
    if not os.path.exists(resume_path):
        print(f"Error: resume.md not found.", file=sys.stderr)
        return None, None
        
    with open(resume_path, "r", encoding="utf-8") as f:
        resume_text = f.read()
        
    # Get job details
    conn = db.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
    job = cursor.fetchone()
    conn.close()
    
    if not job:
        print(f"Error: Job ID {job_id} not found in database.", file=sys.stderr)
        return None, None
        
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
        return None, None
        
    client = Groq(api_key=api_key)
    model_name = config.get_best_model(client)
    print(f"Using Groq model: {model_name}")
    
    # Create tailored directory
    tailored_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tailored")
    os.makedirs(tailored_dir, exist_ok=True)
    
    # 1. Tailor Resume Prompt
    resume_prompt = f"""You are an expert resume optimizer. Your task is to adapt the candidate's resume for a specific job posting.
Rules:
1. DO NOT cut down, summarize, or compress the descriptions. Preserve all technical details, hard metrics (e.g., 8,700 tickets, 500,000 samples, 70% coverage), and specific technologies (Pydantic, Splunk, Playwright, allenai-specter, FAISS, PyTorch, etc.).
2. Do not delete projects or experience bullet points. The tailored resume must remain as comprehensive and detailed as the original. Only re-order, re-prioritize, or slightly rephrase the bullets to align with the job posting's keywords.
3. DO NOT fabricate any experience, company, duration, graduation date, GPA, project, or credential. The resume must remain completely truthful.
4. Keep the markdown formatting neat and clean.

Candidate Resume:
{resume_text}

Job Posting:
Company: {company}
Title: {title}
Description:
{description[:5000]}

Please output the COMPLETE tailored resume in Markdown.
"""

    # 2. Cover Letter Prompt
    cover_prompt = f"""You are an expert career consultant. Write a professional, concise, and compelling Cover Letter (max 300 words) for the candidate.
Rules:
1. Adapt the letter to show genuine interest in the company and explain why their skills match.
2. Rely strictly on existing experiences in the candidate's resume. Do not invent any projects or roles.
3. Do not include placeholders like [Date]. Keep it ready to send, using a modern business format.

Candidate Resume:
{resume_text}

Job Posting:
Company: {company}
Title: {title}
Description:
{description[:5000]}

Please output the cover letter in Markdown.
"""

    try:
        # Generate Resume
        tailored_resume = None
        retries = 0
        max_retries = config.key_manager.get_num_keys()
        
        print("-> Generating tailored resume...")
        while retries < max_retries:
            try:
                res_response = client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "user", "content": resume_prompt}],
                    temperature=0.2
                )
                tailored_resume = res_response.choices[0].message.content
                break
            except Exception as e:
                err_str = str(e).lower()
                if any(term in err_str for term in ["rate_limit", "429", "limit_exceeded", "tokens per day"]):
                    print(f"Rate limit hit during resume tailoring: {e}")
                    retries += 1
                    if retries < max_retries:
                        client = config.cycle_groq_client()
                        model_name = config.get_best_model(client)
                        continue
                raise e
                
        if not tailored_resume:
            raise ValueError("Failed to generate tailored resume.")
        
        # Generate Cover Letter
        tailored_cl = None
        retries = 0
        
        print("-> Generating tailored cover letter...")
        while retries < max_retries:
            try:
                cl_response = client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "user", "content": cover_prompt}],
                    temperature=0.2
                )
                tailored_cl = cl_response.choices[0].message.content
                break
            except Exception as e:
                err_str = str(e).lower()
                if any(term in err_str for term in ["rate_limit", "429", "limit_exceeded", "tokens per day"]):
                    print(f"Rate limit hit during cover letter tailoring: {e}")
                    retries += 1
                    if retries < max_retries:
                        client = config.cycle_groq_client()
                        model_name = config.get_best_model(client)
                        continue
                raise e
                
        if not tailored_cl:
            raise ValueError("Failed to generate tailored cover letter.")
        
        # Save files
        clean_company = "".join([c for c in company if c.isalnum() or c in (' ', '_')]).replace(' ', '_')
        clean_title = "".join([c for c in title if c.isalnum() or c in (' ', '_')]).replace(' ', '_')
        
        resume_filename = f"{clean_company}_{clean_title}_Resume.md"
        cl_filename = f"{clean_company}_{clean_title}_CoverLetter.md"
        
        resume_filepath = os.path.join(tailored_dir, resume_filename)
        cl_filepath = os.path.join(tailored_dir, cl_filename)
        
        with open(resume_filepath, "w", encoding="utf-8") as f:
            f.write(tailored_resume)
            
        with open(cl_filepath, "w", encoding="utf-8") as f:
            f.write(tailored_cl)
            
        print(f"-> Tailored Resume saved to: {resume_filepath}")
        print(f"-> Cover Letter saved to: {cl_filepath}")
        
        # Update db
        db.mark_as_applied(job_id, resume_filepath, cl_filepath)
        
        return resume_filepath, cl_filepath
        
    except Exception as e:
        print(f"Error generating tailored materials: {e}", file=sys.stderr)
        return None, None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tailor.py [job_id]", file=sys.stderr)
        sys.exit(1)
    tailor_materials(sys.argv[1])
