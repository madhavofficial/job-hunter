import os
import re
import sys
from groq import Groq
import db
import config
from pdf_utils import markdown_to_pdf
import github_portfolio


def is_job_description_ambiguous(title: str, description: str) -> tuple[bool, str]:
    """Detects if a job description is ambiguous, multi-track, general development centre,
    or early-career talent pool requiring a broad portfolio presentation.
    """
    t = (title or "").lower()
    d = (description or "").lower()

    # 1. Explicit multi-role, talent pool, or general listing markers
    pooling_markers = [
        "multiple potential roles", "outlines multiple", "multiple roles across",
        "various roles across", "various roles", "considered as openings arise", "general listing",
        "talent pool", "talent pooling", "rotational", "development centre", "development center",
        "idc", "various teams", "multiple teams", "future openings", "early career program",
        "campus hiring", "graduate trainee", "general software engineer", "rotational program",
        "explore different areas", "multiple engineering disciplines"
    ]
    for marker in pooling_markers:
        if marker in d or marker in t:
            return True, f'Explicit multi-role/general marker found: "{marker}"'

    # 2. Cross-disciplinary multi-domain check (touching 3+ disjoint engineering pillars)
    domain_keywords = {
        "Embedded/Mobile/Systems": [
            "android", "aosp", "embedded", "soc", "firmware", "kernel", "sensor", "iot",
            "qualcomm", "device security", "keystore", "selinux", "hardware"
        ],
        "AI/ML/ComputerVision": [
            "deep learning", "computer vision", "nlp", "machine learning", "pytorch",
            "tensorflow", "llm", "generative ai", "gemini", "neural network"
        ],
        "Distributed/BigData/Cloud": [
            "kafka", "spark", "distributed system", "data streaming", "batch processing",
            "hadoop", "microservice", "distributed systems"
        ],
        "FullStack/Web/Backend": [
            "full stack", "fullstack", "react", "node.js", "typescript", "fastapi",
            "flask", "django", "rest api", "web application"
        ],
        "DevOps/Automation/Tooling": [
            "ci/cd", "docker", "kubernetes", "playwright", "automation", "test automation",
            "testing automation", "devops"
        ]
    }
    matched_domains = []
    for domain, kw_list in domain_keywords.items():
        if any(re.search(r"\b" + re.escape(kw) + r"\b", d) for kw in kw_list):
            matched_domains.append(domain)

    if len(matched_domains) >= 3:
        return True, f"Cross-disciplinary role touching {len(matched_domains)} domains: {', '.join(matched_domains)}"

    # 3. Vague/Sparse Description with generic title
    generic_titles = [
        "software engineer", "software developer", "member of technical staff", "associate software engineer",
        "engineering intern", "sde intern", "technology intern", "graduate engineer", "technology analyst"
    ]
    if any(gt in t for gt in generic_titles) and len(d.strip()) < 350:
        return True, f'Vague/sparse description ({len(d.strip())} chars) with generic title "{title}"'

    return False, "Targeted/domain-specific posting"


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

    is_ambiguous, ambiguity_reason = is_job_description_ambiguous(title, description)
    if is_ambiguous:
        print(f"-> Ambiguous / multi-track role detected: {ambiguity_reason}")
        print("-> Applying Broad Versatility Strategy: Maximizing viable projects across diverse domains...")
        project_strategy = f"""2. DYNAMIC PROJECT SELECTION & ALIGNMENT — AMBIGUOUS / MULTI-TRACK / GENERAL JD STRATEGY:
   - DETECTED CONTEXT: The Job Posting is AMBIGUOUS, MULTI-TRACK, or a GENERAL HIRING POOL ({ambiguity_reason}).
   - CORE DIRECTIVE: INCLUDE AS MANY HIGH-SIGNAL, VIABLE PROJECTS AS POSSIBLE (INCLUDE 4 TO 5 DIVERSE PROJECTS) from the candidate's verified pool (Base Resume + GitHub Portfolio).
   - DO NOT limit the resume to a single narrow track or only 2-3 projects. Showcase broad engineering versatility across multiple technical domains:
      * Pillar 1 (Computer Vision / Deep Learning / Embedded AI): 'Sketch Recognition System' (Hierarchical CNN, Squeeze-and-Excitation attention, PyTorch, multi-worker out-of-core streaming)
      * Pillar 2 (Distributed Systems / Big Data / Streaming / Concurrency): '153_Project3_BD' (Distributed Stream & Image Processing with Apache Kafka, Docker, Python)
      * Pillar 3 (Full-Stack / Systems Architecture / Web): 'Ultimate-Trader-Dashboard' (TypeScript, Next.js, WebSockets, PostgreSQL, Docker) or 'University-DBMS-Management-'
      * Pillar 4 (AI Agents / Tooling / Workflow Automation): 'job-hunter' (Agentic automation, multi-source scraping, Pydantic guardrails) or 'CareerTime' (Groq LPU, LangChain)
      * Pillar 5 (Epistemic Multi-Agent Systems / Research / RAG / Graph Clustering): 'A Multi-Agent Generative AI System for Scientific Literature Analysis' (Selected for IEEE SPICES conference, Zenodo DOI: 10.5281/zenodo.22676649, GitHub: https://github.com/GenAI-Scientific-Literature-System/GenAI-Scientific-Literature-System-multi-agent-system, Sentence-BERT, Louvain community clustering, 5-agent verification ensemble, 92.7% accuracy, 89.8% F1) or 'Neuro-Symbolic Platform for Variant Pathogenicity Evaluation'
   - STRICT SINGLE-PAGE FIT RULES:
     * To fit 4 to 5 projects cleanly on ONE page, write EXACTLY 2 to 3 concise, punchy, high-density bullet points per project.
     * Bullet 1: MUST state WHAT the project is and WHAT it does (core product capability and problem solved).
     * Bullets 2-3: Detail deep technical architecture, libraries, concurrency/data flow, performance optimizations, and quantitative metrics (accuracy, latency, throughput, scale).
   - EXPANDED SKILLS: Ensure the Technical Skills section covers the full breadth of languages, frameworks, and tools across all included projects (e.g. Python, TypeScript, Java, C, Kotlin, Scala, PyTorch, Apache Kafka, Next.js, PostgreSQL, Docker, Android)."""
    else:
        print("-> Targeted role detected. Applying Deep Specialization Strategy...")
        project_strategy = """2. DYNAMIC PROJECT SELECTION & ALIGNMENT — TARGETED / SPECIALIZED JD STRATEGY:
   - Carefully review the Job Posting requirements (required languages, frameworks, domain, e.g. DevOps, TypeScript, Full-Stack Web, Backend, Distributed Systems, AI/ML, Data Science, Databases).
   - Compare the candidate's Current Resume Projects with the candidate's Verified GitHub Project Portfolio.
   - Select the 3 to 4 BEST-FITTING projects from the combined pool of projects (Current Resume + GitHub Portfolio).
   - REPLACE less relevant projects on the base resume with stronger-matching GitHub projects where appropriate:
      * For AI / RAG / Agent / NLP / Generative AI / Research / Machine Learning roles -> STRONGLY PRIORITIZE 'A Multi-Agent Generative AI System for Scientific Literature Analysis' (Selected for IEEE SPICES conference, Zenodo DOI: 10.5281/zenodo.22676649, GitHub: https://github.com/GenAI-Scientific-Literature-System/GenAI-Scientific-Literature-System-multi-agent-system, 92.7% accuracy, 89.8% F1) and ensure the IEEE SPICES publication is featured prominently!
      * For DevOps / Cloud / Automation / Tooling roles -> prioritize 'job-hunter'.
      * For Big Data / Data Engineering / Streaming / Spark / Kafka / Distributed Systems / Batch Processing -> prioritize '153_Project3_BD' (Distributed Stream & Image Processing with Apache Kafka, Docker, Python) and 'Forecasting-Bike-Rental-Demand'.
      * For Full-Stack / TypeScript / FinTech / Database roles -> prioritize 'Ultimate-Trader-Dashboard' or 'University-DBMS-Management-'.
      * For Computer Vision / Deep Learning -> prioritize 'Sketch Recognition System'.
      * For Data Science / Regression / Analytics -> prioritize 'Forecasting-Bike-Rental-Demand'.
   - FIRST BULLET EXPLAINS WHAT THE PROJECT DOES: For EVERY project on the resume, the FIRST bullet point MUST clearly state WHAT the project is and WHAT it does (its core product capability, user function, and problem solved). The remaining bullets should then detail the deep engineering architecture, database design, concurrency models, performance optimizations, and quantitative metrics.
   - For each selected project, write 3 to 4 detailed, highly technical bullet points demonstrating real engineering architecture, libraries, and design patterns from its verified documentation."""
    
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
{project_strategy}
   - AUTONOMOUS AMBIGUITY EVALUATION: If the prompt marked this as targeted, but YOU evaluate from the Job Description that the role is actually broad, multi-track, general development centre (e.g. IDC), rotational, or lacks specific single-domain constraints, OVERRIDE and apply the AMBIGUOUS / BROAD JOB DIRECTIVE: include 4 to 5 diverse projects with 2-3 concise, high-density bullets per project to showcase maximum engineering breadth.
2.5. PUBLICATIONS & FLAGSHIP RESEARCH:
   - The candidate co-authored the research paper: 'A Multi-Agent Generative AI System for Scientific Literature Analysis' (Adishree Gupta, Uma D, Madhav Jayam, Sai Roshini Kolla — PES University), which was SELECTED FOR IEEE SPICES (IEEE International Conference on Signal Processing, Informatics, Communication and Energy Systems) with Zenodo DOI: 10.5281/zenodo.22676649 and GitHub: https://github.com/GenAI-Scientific-Literature-System/GenAI-Scientific-Literature-System-multi-agent-system.
   - ALWAYS include this publication/project prominently on the tailored resume! Either in a dedicated '## Publications' section or as a flagship project, explicitly stating:
     * **NO DUPLICATION**: If you include this research under '## Publications', DO NOT also list it under '## Selected Projects'. Pick other top engineering projects for the projects section so there is zero redundancy.
     * **Conference Acceptance**: Selected for **IEEE SPICES** (IEEE International Conference on Signal Processing, Informatics, Communication and Energy Systems).
     * **Links**: DOI: [10.5281/zenodo.22676649](https://doi.org/10.5281/zenodo.22676649) | GitHub: [GenAI-Scientific-Literature-System](https://github.com/GenAI-Scientific-Literature-System/GenAI-Scientific-Literature-System-multi-agent-system)
     * **NEVER condense this into a single vague line**. When including this publication/project, write 3 to 4 rich, technically rigorous bullets using clean, readable symbols (avoid raw unescaped LaTeX math macros like \mathcal or \text):
       1. Overcame parametric staleness and citation hallucination in flat RAG/LLMs by synthesizing 300–800 live scholarly papers (arXiv, PubMed, Semantic Scholar) per query.
       2. Constructed Sentence-BERT cosine similarity graphs partitioned via Louvain modularity clustering (**silhouette 0.71**) with normalized Laplacian spectral fallback to isolate thematic sub-corpora.
       3. Engineered a concurrent 5-agent ensemble: Claim Extraction (Agent 1 with Hallucination Guard), Evidence Mapping (Agent 2), Study Reliability Scoring (Agent 3 evaluating clinical trial design, sample size N, p < 0.05), Cross-Paper Consensus/Conflict Matrix (Agent 4), and Uncertainty Prioritization (Agent 5 via balance entropy contention).
       4. Deployed composite verification scoring Score(c, e) = 0.6 * sim(c, e) + 0.4 * rel(e), achieving **92.7% accuracy** and **89.8% F1** (+14.2% F1 over LLMs, +6.8% F1 over RAG, p < 0.001).
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
        
        # Save files in dedicated company directory with Madhav_Jayam_ naming scheme
        clean_company = "".join([c for c in company if c.isalnum() or c in (' ', '_')]).replace(' ', '_')
        clean_title = "".join([c for c in title if c.isalnum() or c in (' ', '_')]).replace(' ', '_')
        clean_company = re.sub(r'_+', '_', clean_company).strip('_')
        clean_title = re.sub(r'_+', '_', clean_title).strip('_')

        company_dir = os.path.join(tailored_dir, clean_company)
        os.makedirs(company_dir, exist_ok=True)

        resume_filename = f"Madhav_Jayam_{clean_company}_{clean_title}_Resume.md"
        resume_pdf_filename = f"Madhav_Jayam_{clean_company}_{clean_title}_Resume.pdf"

        resume_filepath = os.path.join(company_dir, resume_filename)
        resume_pdf_filepath = os.path.join(company_dir, resume_pdf_filename)

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
