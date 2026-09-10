import os
import re
import sys
from groq import Groq
import db
import config
from pdf_utils import markdown_to_pdf
import github_portfolio


PREFERRED_OPENROUTER_MODELS = (
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "qwen/qwen3-coder:free",
    "openrouter/free",
)


def ensure_selected_project_github_links(markdown: str, portfolio: list[dict]) -> str:
    """Ensure selected GitHub projects have their verified repository links.

    The model is instructed to emit links, but its Markdown output is not
    guaranteed to follow every formatting rule. Only URLs from the inspected
    portfolio are inserted; unmatched headings are left untouched.
    """
    if not markdown or not portfolio:
        return markdown

    def normalize(value: str) -> str:
        value = re.sub(r"\[[^]]+\]\([^)]*\)", "", value)
        value = re.sub(r"\([^)]*\)", "", value)
        return re.sub(r"[^a-z0-9]+", "", value.lower())

    projects = []
    for project in portfolio:
        url = (project.get("url") or "").strip()
        if not url or "github.com/" not in url.lower():
            continue
        names = [project.get("name", ""), project.get("display_name", ""), project.get("full_name", "")]
        names = [normalize(name) for name in names if name]
        if names:
            projects.append((names, url))

    if not projects:
        return markdown

    lines = markdown.splitlines()
    output = []
    in_selected_projects = False
    for index, line in enumerate(lines):
        heading_match = re.match(r"^##\s+(.+?)\s*$", line)
        if heading_match:
            in_selected_projects = normalize(heading_match.group(1)).startswith("selectedprojects")

        if in_selected_projects and re.match(r"^###\s+", line):
            heading_name = normalize(re.sub(r"^###\s+", "", line))
            matched_url = None
            matched_length = 0
            for names, url in projects:
                for name in names:
                    if name and (name in heading_name or heading_name in name) and len(name) > matched_length:
                        matched_url = url
                        matched_length = len(name)

            if matched_url:
                next_heading = len(lines)
                for lookahead in range(index + 1, len(lines)):
                    if re.match(r"^#{1,3}\s+", lines[lookahead]):
                        next_heading = lookahead
                        break
                section_text = "\n".join(lines[index + 1:next_heading])
                if "github.com/" not in section_text.lower():
                    output.append(line)
                    output.append(f"*GitHub: {matched_url}*")
                    continue

        output.append(line)

    return "\n".join(output) + ("\n" if markdown.endswith("\n") else "")


def ensure_career_objective_target(markdown: str, company: str, title: str) -> str:
    """Ensure the Career Objective names the exact target company and role."""
    if not markdown:
        markdown = ""

    company = " ".join((company or "").split())
    title = " ".join((title or "").split())
    if not company or not title:
        return markdown

    target_line = f"Targeting the **{title}** position at **{company}**."
    lines = markdown.splitlines()
    objective_index = None
    for index, line in enumerate(lines):
        heading_text = re.sub(r"[*_`]", "", line.strip())
        if re.match(r"^#{1,3}\s+career objective\s*$", heading_text, re.IGNORECASE):
            objective_index = index
            break

    if objective_index is None:
        insert_at = 1 if lines and re.match(r"^#\s+", lines[0]) else 0
        lines[insert_at:insert_at] = ["## Career Objective", target_line, ""]
        return "\n".join(lines) + ("\n" if markdown.endswith("\n") else "")

    next_heading = len(lines)
    for index in range(objective_index + 1, len(lines)):
        if re.match(r"^#{1,3}\s+", lines[index]):
            next_heading = index
            break
    objective_text = "\n".join(lines[objective_index + 1:next_heading]).lower()
    if company.lower() in objective_text and title.lower() in objective_text:
        return markdown

    lines.insert(objective_index + 1, target_line)
    return "\n".join(lines) + ("\n" if markdown.endswith("\n") else "")


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
      * Pillar 5 (Epistemic Multi-Agent Systems / Research / Clinical RAG / Graph Clustering): 'GLAS-Med: Evidence-Grounded Clinical Literature Synthesis' (GitHub: https://github.com/madhavofficial/evidence-grounded-clinical-literature-synthesis) — An advanced clinical and production microservice enhancement of the IEEE SPICES research paper adding PICO tuple projection, Oxford CEBM evidence hierarchy classification, 8-factor study reliability scoring, and 9-microservice deployment (FastAPI, MongoDB, Neo4j, FAISS, Docker) OR 'Neuro-Symbolic Platform for Variant Pathogenicity Evaluation'
     - DEPTH, TECHNICAL SUBSTANCE & IMPACT RULES:
      * There is NO artificial 1-page restriction — prioritize technical substance, architectural depth, and quantitative metrics over arbitrary length limits. It is far more important that the reader understands the project than the size of the resume. For each project, write 3 to 4 comprehensive, punchy, high-density bullet points.
      * Bullet 1: MUST state WHAT the project is and WHAT it does (core product capability and problem solved).
      * Bullets 2-4: Detail deep technical architecture, libraries, concurrency/data flow, performance optimizations, and quantitative metrics (accuracy, latency, throughput, scale).
   - EXPANDED SKILLS: Ensure the Technical Skills section covers the full breadth of languages, frameworks, and tools across all included projects (e.g. Python, TypeScript, Java, C, Kotlin, Scala, PyTorch, Apache Kafka, Next.js, PostgreSQL, Docker, Android)."""
    else:
        print("-> Targeted role detected. Applying Deep Specialization Strategy...")
        project_strategy = """2. DYNAMIC PROJECT SELECTION & ALIGNMENT — TARGETED / SPECIALIZED JD STRATEGY:
   - Carefully review the Job Posting requirements (required languages, frameworks, domain, e.g. DevOps, TypeScript, Full-Stack Web, Backend, Distributed Systems, AI/ML, Data Science, Databases).
   - Compare the candidate's Current Resume Projects with the candidate's Verified GitHub Project Portfolio.
   - Select the 3 to 4 BEST-FITTING projects from the combined pool of projects (Current Resume + GitHub Portfolio).
   - REPLACE less relevant projects on the base resume with stronger-matching GitHub projects where appropriate:
      * For AI / RAG / Agent / NLP / Generative AI / Research / Machine Learning roles -> STRONGLY PRIORITIZE 'GLAS-Med: Evidence-Grounded Clinical Literature Synthesis' (GitHub: https://github.com/madhavofficial/evidence-grounded-clinical-literature-synthesis) as an advanced clinical & production engineering enhancement of the IEEE SPICES paper (featuring PICO extraction, Oxford CEBM evidence tiers, 8-factor reliability scoring, Neo4j knowledge graphs, and microservices), alongside 'Neuro-Symbolic Platform for Variant Pathogenicity Evaluation'.
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
   - AUTONOMOUS AMBIGUITY EVALUATION: If the prompt marked this as targeted, but YOU evaluate from the Job Description that the role is actually broad, multi-track, general development centre (e.g. IDC), rotational, or lacks specific single-domain constraints, OVERRIDE and apply the AMBIGUOUS / BROAD JOB DIRECTIVE: include 4 to 5 diverse projects with 3-4 detailed, high-density bullets per project to showcase maximum engineering breadth.
2.5. PUBLICATIONS & FLAGSHIP RESEARCH:
   - The candidate co-authored the research paper: 'A Multi-Agent Generative AI System for Scientific Literature Analysis' (Adishree Gupta, Uma D, Madhav Jayam, Sai Roshini Kolla — PES University), which was SELECTED FOR IEEE SPICES (IEEE International Conference on Signal Processing, Informatics, Communication and Energy Systems) with Zenodo DOI: 10.5281/zenodo.22676649 and GitHub: https://github.com/GenAI-Scientific-Literature-System/GenAI-Scientific-Literature-System-multi-agent-system.
   - ALWAYS include this publication prominently in the '## Publications' section!
     * **Conference Acceptance**: Selected for **IEEE SPICES** (IEEE International Conference on Signal Processing, Informatics, Communication and Energy Systems).
     * **Links**: DOI: [10.5281/zenodo.22676649](https://doi.org/10.5281/zenodo.22676649) | GitHub: [GenAI-Scientific-Literature-System](https://github.com/GenAI-Scientific-Literature-System/GenAI-Scientific-Literature-System-multi-agent-system)
     * **NEVER condense this into a single vague line, and DO NOT include raw math formulas**. Focus purely on system architecture and pipeline engineering:
       1. Built an end-to-end, evidence-grounded multi-agent system that synthesizes scientific literature by querying live scholarly databases (arXiv, PubMed, Semantic Scholar) and ingesting **300–800 papers** per query to eliminate citation hallucination.
       2. Engineered semantic similarity graph clustering over dense document representations to segment retrieved literature into cohesive thematic sub-corpora and filter cross-domain noise before agent dispatch.
       3. Coordinated five specialized agents running concurrently to extract declarative claims (with an automated Hallucination Guard), map empirical evidence, evaluate study methodological reliability, detect cross-paper consensus vs. contradictions, and prioritize unresolved research frontiers.
       4. Demonstrated **92.7% accuracy** and **89.8% F1 score** across multi-domain scientific benchmarks, outperforming standalone LLMs by **+14.2% F1** and standard RAG baselines by **+6.8% F1**.
   - RESEARCH REPOSITORY vs. PRODUCTION ENHANCEMENT IN SELECTED PROJECTS:
     * In '## Publications', feature the academic paper as published at IEEE SPICES.
     * In '## Selected Projects', if you include a project associated with this research, DO NOT duplicate the basic publication title or bullets! Instead, feature its full clinical and production engineering enhancement:
       `### GLAS-Med: Evidence-Grounded Clinical Literature Synthesis (Clinical & Production Enhancement of IEEE SPICES Architecture)`
       `*GitHub: https://github.com/madhavofficial/evidence-grounded-clinical-literature-synthesis*`
       Explain clearly that this is an advanced clinical and production microservice enhancement of the project associated with the IEEE SPICES paper. Detail the extra capabilities (WITHOUT math formulas):
       1. **Clinical Claim Extraction & PICO Projection**: Extracted clinical claims and projected unstructured biomedical abstracts into Population, Intervention, Comparator, and Outcome (PICO) assertions for evidence-based medicine.
       2. **5-Tier Oxford CEBM Hierarchy**: Stratified clinical evidence into Oxford Centre for Evidence-Based Medicine (CEBM) Levels 1-5, giving higher evidential weight to randomized controlled trials (RCTs) over observational studies.
       3. **8-Factor Study Reliability & Quarantine**: Evaluated study reliability across 8 methodological factors (sample size, double-blinding, randomization, follow-up, statistical power, funding bias, preregistration, journal impact), automatically quarantining low-reliability studies from consensus aggregation.
       4. **Medical Knowledge Graph & Epistemic Uncertainty**: Constructed clinical knowledge graphs with Louvain community detection to detect consensus and rank unresolved clinical controversies and unproven therapies.
       5. **Production Microservice Architecture**: Built a 9-microservice backend deployed via Docker Compose with FastAPI, MongoDB document store, Neo4j graph database, and FAISS vector retrieval.
3. SKILLS SECTION: Update the Technical Skills section to highlight the exact languages and tools used across the selected projects and experience (e.g., add TypeScript, Docker, Prisma, etc. if featuring TypeScript/Full-Stack projects).
4. ZERO FABRICATION & NO LENGTH RESTRICTIONS: Do NOT invent non-existent projects, companies, durations, graduation date (May 2027), or credentials. Rely strictly on facts in the candidate's resume and GitHub portfolio. Do NOT include GPA on the resume. There is NO artificial 1-page restriction — prioritize thorough understanding, architectural depth, and complete explanations over resume length. It is much more important that the reader understands the project than the size of the resume.
5. FORMATTING & TYPOGRAPHY:
   - Heavily utilize markdown bolding (**bold**) for all key metrics, numbers, core technologies, and frameworks across every bullet point (e.g. **8,700** tickets, **70%** coverage, **40%** latency reduction, **TypeScript**, **PostgreSQL**, **Prisma ORM**, **Docker**).
   - In the `## Career Objective` section, explicitly name the exact target company (**{company}**) and position (**{title}**) for this tailored resume.
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

        # 1. Primary: Try OpenRouter in explicit capability order.
        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        if openrouter_key:
            from openai import OpenAI
            or_client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=openrouter_key, timeout=120)
            configured_openrouter_model = os.getenv("OPENROUTER_MODEL")
            openrouter_models = ([configured_openrouter_model] if configured_openrouter_model else list(PREFERRED_OPENROUTER_MODELS))
            for openrouter_model in openrouter_models:
                try:
                    print(f"-> Trying OpenRouter model: {openrouter_model}")
                    or_resp = or_client.chat.completions.create(
                        model=openrouter_model,
                        messages=[{"role": "user", "content": resume_prompt}],
                        temperature=0.2,
                        timeout=120,
                    )
                    if or_resp and or_resp.choices and or_resp.choices[0].message:
                        tailored_resume = or_resp.choices[0].message.content
                        break
                except Exception as e:
                    print(f"Warning: OpenRouter model {openrouter_model} failed: {e}", file=sys.stderr)
            if not tailored_resume:
                print("Warning: all OpenRouter models failed. Falling back to Groq cluster...", file=sys.stderr)

        # 2. Fallback: Groq Multi-Key & Model Cluster
        if not tailored_resume:
            candidate_models = [model_name] + [m for m in config.get_fallback_models() if m != model_name]
            print("-> Generating tailored resume via Groq cluster...")
            for active_model in candidate_models:
                retries = 0
                max_retries = max(1, config.key_manager.get_num_keys())
                while retries < max_retries:
                    try:
                        res_response = client.chat.completions.create(
                            model=active_model,
                            messages=[{"role": "user", "content": resume_prompt}],
                            temperature=0.2,
                            timeout=120,
                        )
                        tailored_resume = res_response.choices[0].message.content
                        break
                    except Exception as e:
                        err_str = str(e).lower()
                        if "expired_api_key" in err_str or ("401" in err_str and "invalid api key" in err_str):
                            print(f"Invalid API key encountered. Dropping key and cycling...")
                            client = config.cycle_groq_client(remove_current=True)
                            retries += 1
                            continue
                        if any(term in err_str for term in ["request too large", "413", "tokens per minute", "tpm", "limit 8000", "context_length_exceeded", "request_too_large"]):
                            print(f"Prompt exceeded TPM/context limit for {active_model}. Falling back to next model...")
                            break
                        if any(term in err_str for term in ["rate_limit", "429", "limit_exceeded", "tokens per day"]):
                            print(f"Rate limit hit on {active_model} during resume tailoring: {e}")
                            retries += 1
                            if retries < max_retries:
                                client = config.cycle_groq_client()
                                continue
                            else:
                                print(f"-> All keys exhausted for {active_model}. Falling back to next model...")
                                break
                        print(f"Error on {active_model}: {e}. Falling back to next model...")
                        break
                if tailored_resume:
                    break
                
        if not tailored_resume:
            raise ValueError("Failed to generate tailored resume after trying all keys and fallback models.")

        tailored_resume = ensure_selected_project_github_links(tailored_resume, portfolio)
        tailored_resume = ensure_career_objective_target(tailored_resume, company, title)
        
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
