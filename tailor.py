import os
import re
import sys
from groq import Groq
import db
import config
from pdf_utils import markdown_to_pdf
import github_portfolio
import profiles


PREFERRED_OPENROUTER_MODELS = (
    "nex-agi/nex-n2.5-mini:free",
    "nex-agi/nex-n2.5-pro:free",
    "openrouter/free",
)


def strip_certifications(markdown: str) -> str:
    """Strip Certifications section and unshared course credentials from resume markdown."""
    if not markdown:
        return ""

    lines = markdown.splitlines()
    output = []
    in_certifications = False

    for line in lines:
        cleaned = re.sub(r"[*_`]", "", line).strip().lower()
        if re.match(r"^#{1,3}\s+(certifications?|courses?\s+(?:&|and)\s+certifications?|certifications?\s+(?:&|and)\s+licenses?|licenses?\s+(?:&|and)\s+certifications?)\s*$", cleaned):
            in_certifications = True
            # Strip trailing horizontal rule before certifications if present
            while output and (output[-1].strip() == "---" or not output[-1].strip()):
                output.pop()
            continue

        if in_certifications:
            # End of certifications when another major section or footer begins
            if re.match(r"^#{1,3}\s+", line) or line.strip().startswith("*Prepared for"):
                in_certifications = False
                output.append("")
                output.append("---")
                output.append("")
                output.append(line)
            continue

        output.append(line)

    result = "\n".join(output)
    result = re.sub(r"\n(?:---\s*\n)+---\s*\n", "\n---\n", result)
    return result.strip() + "\n"


def scrub_unverified_metrics(markdown: str, profile_id: str = "") -> str:
    """Scrub known hallucinated metrics from candidate resume."""
    if not markdown or profile_id != "mahika":
        return markdown

    # Strip hallucinated test coverage percentages (e.g. >90%, >95%)
    markdown = re.sub(
        r"(?:covering\s+)?(?:>|≥|approximately|~)?\s*\d{2,3}\s*%\s*(?:of\s+service\s+layer\s+methods|test\s+coverage)",
        "comprehensive unit and integration test coverage",
        markdown,
        flags=re.IGNORECASE
    )
    # Strip hallucinated TA proficiency percentages and student counts
    markdown = re.sub(
        r"(?:improving|improved|enhancing|strengthening)\s+(?:student\s+)?(?:coding\s+proficiency|code\s+quality)?\s*(?:by\s+)?(?:≈|~|approximately)?\s*\d{1,2}\s*%\s*(?:\([^)]*assessment\s+scores[^)]*\)|across\s+(?:≈|~|approximately)?\s*\d+\s+students)?",
        "strengthening students' foundational programming concepts",
        markdown,
        flags=re.IGNORECASE
    )
    markdown = re.sub(
        r"(?:by\s+)?(?:≈|~|approximately)?\s*\d{1,2}\s*%\s*\([^)]*assessment\s+scores[^)]*\)",
        "strengthening foundational programming concepts",
        markdown,
        flags=re.IGNORECASE
    )
    markdown = re.sub(
        r"across\s+(?:≈|~|approximately)?\s*\d+\s+students",
        "for first-year B.Tech students",
        markdown,
        flags=re.IGNORECASE
    )
    # Strip hallucinated TAMS registration percentages
    markdown = re.sub(
        r"(?:increasing|increased|boosting)\s+participant\s+registrations\s+(?:by\s+)?(?:≈|~|approximately)?\s*\d{1,2}\s*%\s*(?:through\s+targeted\s+campaigns)?",
        "driving participant outreach and technical event engagement",
        markdown,
        flags=re.IGNORECASE
    )
    markdown = re.sub(
        r"increasing\s+participant\s+registrations\s+by\s+(?:≈|~|approximately)?\s*\d{1,2}\s*%\s*(?:through\s+targeted\s+campaigns)?",
        "driving participant outreach and technical event engagement",
        markdown,
        flags=re.IGNORECASE
    )
    # Strip hallucinated TPS (e.g. 200 TPS)
    markdown = re.sub(
        r"\s*\((?:simulated\s+)?\d+\s*TPS\)",
        "",
        markdown,
        flags=re.IGNORECASE
    )
    # Strip hallucinated AUC in Matcher
    markdown = re.sub(
        r"\s*\((?:AUC|ROC-AUC)\s*=\s*0\.\d+\)",
        "",
        markdown,
        flags=re.IGNORECASE
    )
    # Strip hallucinated vulnerability counts (e.g. 12 critical vulnerabilities)
    markdown = re.sub(
        r"identifying\s+and\s+remediating\s+\d+\s+critical\s+vulnerabilities",
        "identifying and remediating application security vulnerabilities",
        markdown,
        flags=re.IGNORECASE
    )

    # 1. Strip 'robotics' from Career Objective
    def _clean_obj(m):
        block = m.group(0)
        cleaned = re.sub(r",?\s*(?:embedded\s+)?robotics\s*,?", ", ", block, flags=re.IGNORECASE)
        cleaned = re.sub(r"\band\s+robotics\b", "and full-stack development", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r",\s*,", ", ", cleaned)
        cleaned = re.sub(r",\s*and\b", " and", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        return cleaned

    markdown = re.sub(r"##\s*Career Objective.*?(?=\n##|\Z)", _clean_obj, markdown, flags=re.DOTALL | re.IGNORECASE)

    # 2. Enforce explicit long forms ONLY for the requested terms
    markdown = re.sub(r"\bDBMS\b", "Database management systems", markdown)
    markdown = re.sub(r"\bGenerative AI(?!\s+and\s+applications)\b", "Generative AI and applications", markdown, flags=re.IGNORECASE)
    markdown = re.sub(r"\bB\.?\s*Tech\b", "Bachelor of Technology", markdown)

    # 3. Clean all UTF-8 Mojibake and enforce standard ASCII
    markdown = markdown.replace("‚Äî", "-").replace("‚Üí", "->").replace("‚â•", ">=")
    markdown = markdown.replace("â€\"", "-").replace("â†'", "->").replace("â‰¥", ">=")
    markdown = markdown.replace("â€“", "-").replace("â€™", "'").replace("â€œ", '"').replace("â€\x9d", '"')
    markdown = markdown.replace("—", "-").replace("–", "-").replace("‑", "-")
    markdown = markdown.replace("→", "->").replace("←", "<-").replace("≥", ">=").replace("≤", "<=")
    markdown = markdown.replace("\u202f", " ").replace("\u00a0", " ")

    # 4. Remove banned projects if present
    markdown = re.sub(r"###\s*.*?(?:PC\s+Parts|University\s+Database).*?(?=\n###|\n##|\Z)", "", markdown, flags=re.DOTALL | re.IGNORECASE)

    return markdown


def ensure_gpa(markdown: str, profile=None) -> str:
    """Ensure candidate's GPA is present under Education if required by profile."""
    if not markdown or not profile or not getattr(profile, "include_gpa", False):
        return markdown

    gpa_text = getattr(profile, "gpa_text", None)
    if not gpa_text:
        return markdown

    if "8.06" in markdown or "distinction scholarship" in markdown.lower():
        return markdown

    lines = markdown.splitlines()
    output = []
    in_education = False
    gpa_inserted = False

    for line in lines:
        cleaned = re.sub(r"[*_`]", "", line).strip().lower()
        if re.match(r"^#{1,3}\s+education\s*$", cleaned):
            in_education = True

        output.append(line)

        if in_education and not gpa_inserted:
            if "pes university" in line.lower():
                output.append(f"- **CGPA**: **8.06 (Sem 6)** | **Distinction Scholarship** (Semesters 1, 3, 4, 5, 6)")
                gpa_inserted = True

        if in_education and re.match(r"^#{1,3}\s+", line) and not re.match(r"^#{1,3}\s+education\s*$", cleaned):
            in_education = False

    return "\n".join(output) + ("\n" if markdown.endswith("\n") else "")


def ensure_selected_project_github_links(markdown: str, portfolio: list[dict], profile=None) -> str:
    """Ensure selected projects have strictly verified GitHub repository links.

    1. If a project has a verified repository URL:
       - Ensures the exact verified repository URL is placed beneath the project heading.
       - Replaces any wrong, hallucinated, or placeholder URLs (such as /Portfolio).
    2. If a project does NOT have a verified repository URL:
       - Removes any hallucinated or placeholder GitHub lines under that project.
    """
    if not markdown:
        return ""

    def normalize(value: str) -> str:
        value = re.sub(r"\[[^]]+\]\([^)]*\)", "", value)
        value = re.sub(r"\([^)]*\)", "", value)
        return re.sub(r"[^a-z0-9]+", "", value.lower())

    projects = []
    if portfolio:
        for project in portfolio:
            url = (project.get("url") or "").strip()
            if not url or "github.com/" not in url.lower():
                continue
            if "/portfolio" in url.lower():
                continue
            names = [project.get("name", ""), project.get("display_name", ""), project.get("full_name", "")]
            names = [normalize(name) for name in names if name]
            if names:
                projects.append((names, url))

    KNOWN_PROJECT_URLS = {
        "neuro": "https://github.com/madhavofficial/neuro_capstone",
        "symbolic": "https://github.com/madhavofficial/neuro_capstone",
        "pathogenicity": "https://github.com/madhavofficial/neuro_capstone",
        "sketch": "https://github.com/madhavofficial/Drawing-A-New-Way-To-Search-ML-",
        "drawing": "https://github.com/madhavofficial/Drawing-A-New-Way-To-Search-ML-",
        "careertime": "https://github.com/madhavofficial/CareerTime",
        "career": "https://github.com/madhavofficial/CareerTime",
        "glas": "https://github.com/madhavofficial/evidence-grounded-clinical-literature-synthesis",
        "clinical": "https://github.com/madhavofficial/evidence-grounded-clinical-literature-synthesis",
        "kafka": "https://github.com/varunnhn/153_Project3_BD",
        "stream": "https://github.com/varunnhn/153_Project3_BD",
        "153_project3_bd": "https://github.com/varunnhn/153_Project3_BD",
        "bike": "https://github.com/madhavofficial/Forecasting-Bike-Rental-Demand",
        "rental": "https://github.com/madhavofficial/Forecasting-Bike-Rental-Demand",
        "trader": "https://github.com/madhavofficial/Ultimate-Trader-Dashboard-GitHub-Repository-Structure",
        "trading": "https://github.com/madhavofficial/Ultimate-Trader-Dashboard-GitHub-Repository-Structure",
        "watchlist": "https://github.com/madhavofficial/Ultimate-Trader-Dashboard-GitHub-Repository-Structure",
        "hunter": "https://github.com/madhavofficial/job-hunter",
        "caregiver": "https://github.com/madhavofficial/Caregiver-Coordination-Hub",
        "arena": "https://github.com/madhavofficial/oa-arena-windows",
    }

    known_urls = getattr(profile, "known_project_urls", None)
    if known_urls is None and isinstance(profile, dict):
        known_urls = profile.get("known_project_urls")
    if known_urls is None:
        known_urls = KNOWN_PROJECT_URLS

    def is_github_line(text: str) -> bool:
        t = text.strip()
        if re.search(r"^\s*\*?\[?(?:github|repo|repository)\]?[:\s]+<?(https?://[^\s>]+)>?\*?\s*$", t, re.I):
            return True
        if "github.com/" in t.lower() and (t.startswith("*") or t.startswith("[") or t.startswith("- [GitHub]")):
            return True
        if re.match(r"^\s*\*?(?:no\s+public\s+(?:repository|repo)|private\s+repo(?:sitory)?)\*?\s*$", t, re.I):
            return True
        return False

    lines = markdown.splitlines()
    output = []
    in_selected_projects = False
    current_matched_url = None
    url_handled_for_project = False

    i = 0
    while i < len(lines):
        line = lines[i]
        heading_match = re.match(r"^##\s+(.+?)\s*$", line)
        if heading_match:
            norm_heading = normalize(heading_match.group(1))
            in_selected_projects = any(kw in norm_heading for kw in ["selectedprojects", "academicengineeringprojects", "projects"])
            current_matched_url = None
            url_handled_for_project = False
            output.append(line)
            i += 1
            continue

        if in_selected_projects and re.match(r"^###\s+", line):
            heading_name = normalize(re.sub(r"^###\s+", "", line))
            matched_url = None
            matched_length = 0

            # 1. Match against portfolio
            for names, url in projects:
                for name in names:
                    if name and (name in heading_name or heading_name in name) and len(name) > matched_length:
                        matched_url = url
                        matched_length = len(name)

            # 2. Match against profile known_urls
            if not matched_url:
                tokens = re.findall(r"[a-z0-9]{3,}", re.sub(r"\([^)]*\)", "", line).lower())
                for t in tokens:
                    if t in known_urls:
                        matched_url = known_urls[t]
                        break

            if matched_url and "/portfolio" in matched_url.lower():
                matched_url = None

            current_matched_url = matched_url
            output.append(line)

            # Look ahead for an existing link line
            next_idx = i + 1
            has_existing_link = False
            while next_idx < len(lines) and not lines[next_idx].strip():
                next_idx += 1

            if next_idx < len(lines) and is_github_line(lines[next_idx]):
                has_existing_link = True

            if matched_url:
                output.append(f"*GitHub: {matched_url}*")
                url_handled_for_project = True
                if has_existing_link:
                    i = next_idx + 1
                    continue
            else:
                url_handled_for_project = True
                if has_existing_link:
                    i = next_idx + 1
                    continue

            i += 1
            continue

        if in_selected_projects and is_github_line(line):
            if current_matched_url and not url_handled_for_project:
                output.append(f"*GitHub: {current_matched_url}*")
                url_handled_for_project = True
            # Drop unverified or duplicate link lines
            i += 1
            continue

        output.append(line)
        i += 1

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


def tailor_materials(job_id: str, profile_name: str = "madhav"):
    db.init_db()
    profile = profiles.get_profile(profile_name)
    
    # Load resume
    resume_path = profile.resume_path
    if not os.path.exists(resume_path):
        if profile.id == "madhav" and os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "resume.md")):
            resume_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resume.md")
        else:
            print(f"Error: resume file {resume_path} not found.", file=sys.stderr)
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

    # Fetch GitHub portfolio for this candidate profile
    print(f"-> Fetching {profile.name}'s GitHub portfolio for dynamic project alignment...")
    portfolio = github_portfolio.fetch_github_portfolio(profile=profile)
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
    
    print(f"Tailoring application materials for {profile.name}: '{title}' at '{company}'...")

    is_ambiguous, ambiguity_reason = is_job_description_ambiguous(title, description)
    if profile.id == "mahika":
        if is_ambiguous:
            print(f"-> Ambiguous / multi-track role detected for {profile.name}: {ambiguity_reason}")
            print("-> Applying Broad Versatility Strategy: Maximizing viable projects across diverse domains...")
            project_strategy = f"""2. DYNAMIC PROJECT SELECTION & ALIGNMENT — AMBIGUOUS / MULTI-TRACK / GENERAL JD STRATEGY:
   - DETECTED CONTEXT: The Job Posting is AMBIGUOUS, MULTI-TRACK, or a GENERAL HIRING POOL ({ambiguity_reason}).
   - CORE DIRECTIVE: INCLUDE AS MANY HIGH-SIGNAL, VIABLE PROJECTS AS POSSIBLE (INCLUDE 4 TO 5 DIVERSE PROJECTS) from the candidate's verified pool (Base Resume + Project Portfolio).
   - DO NOT limit the resume to a single narrow track or only 2-3 projects. Showcase broad engineering versatility across multiple technical domains:
       * Pillar 1 (Bioinformatics / AI / Structural Biology): 'Capstone Project: AI for Neurodegenerative Protein Analysis & Pathogenicity Reasoning' (AlphaFold 3D PDB structures, BioPython ShrakeRupley SASA, DSSP secondary structure, AlphaMissense evolutionary AI, MyVariant.info, OpenTargets clinical evidence)
       * Pillar 2 (NLP / Machine Learning / Semantic Matching / GenAI): 'Resume-JD Semantic Matcher' (ATS-style matcher, 5-agent pipeline, dual XGBoost models on 7,751 pairs, SBERT embeddings, FAISS vector DB with 2,831 skills, FLAN-T5-small explanations, SHAP)
       * Pillar 3 (Robotics / Computer Vision / Edge AI): 'Autonomous Robotics: Dual-Pipeline Visual Servoing & Odometry' (ROS 2, Arduino, Lucas-Kanade optical flow, HSV fire tracking, RViz2) OR 'Interactive Deep Learning Drawing Classifier' (TensorFlow/Keras custom CNN, 86.55% on QuickDraw 50 categories)
       * Pillar 4 (Enterprise Systems / OOP Architecture / Java): 'Enterprise Loan Management System' (Java SE, MVC, MySQL, 5 GoF design patterns: Chain of Responsibility, Decorator, Observer, Factory, Singleton; Data Export & System Reporting) OR 'Mini-UnionFS' (C, FUSE 3, layered filesystem, CoW, whiteouts)
       * Pillar 5 (Web Platforms / Testing / CI/CD): 'Personal Wealth Management Application' (React, Flask, SQLite, Cypress, Jest, pytest, Bandit, GitHub Actions CI/CD)
    - DEPTH, TECHNICAL SUBSTANCE & IMPACT RULES:
       * There is NO artificial 1-page restriction — prioritize technical substance, architectural depth, and quantitative metrics over arbitrary length limits. For each project, write 3 to 4 comprehensive, punchy, high-density bullet points.
       * Bullet 1: MUST state WHAT the project is and WHAT it does (core product capability and problem solved).
       * Bullets 2-4: Detail deep technical architecture, libraries, concurrency/data flow, and performance optimizations. Include ONLY quantitative metrics that are explicitly documented in the candidate's base resume or portfolio. NEVER invent or hallucinate metrics, percentages, test counts, or benchmarks.
    - EXPANDED SKILLS: Ensure the Technical Skills section covers the full breadth of languages, frameworks, and tools across all included projects (e.g. Python, Java, C, JavaScript, SQL, HTML/CSS, PyTorch, TensorFlow, Scikit-learn, XGBoost, SBERT, FAISS, FLAN-T5, SHAP, BioPython, ROS2, OpenCV, Arduino, FUSE, React, Flask, SQLite, MySQL, Cypress, Jest, pytest, Bandit, Docker, CI/CD)."""
        else:
            print(f"-> Targeted role detected for {profile.name}. Applying Deep Specialization Strategy...")
            project_strategy = """2. DYNAMIC PROJECT SELECTION & ALIGNMENT — TARGETED / SPECIALIZED JD STRATEGY:
   - Carefully review the Job Posting requirements (required languages, frameworks, domain, e.g. AI/ML, NLP, Computer Vision, Robotics, Backend, Full-Stack, Java, Systems, Databases, QA/Testing).
   - Compare the candidate's Current Resume Projects with the candidate's Verified Project Portfolio.
   - Select the 3 to 4 BEST-FITTING projects from the combined pool of projects (Current Resume + Portfolio).
   - REPLACE less relevant projects on the base resume with stronger-matching portfolio projects where appropriate:
      * For AI / RAG / Agent / NLP / Generative AI / Research / Machine Learning roles -> STRONGLY PRIORITIZE 'Capstone Project: AI for Neurodegenerative Protein Analysis & Pathogenicity Reasoning' (AlphaFold structures, BioPython SASA/DSSP, AlphaMissense, MyVariant.info, OpenTargets) and 'Resume-JD Semantic Matcher' (5-agent pipeline, XGBoost on 7,751 pairs, SBERT, FAISS with 2,831 skills, FLAN-T5, SHAP).
      * For Robotics / Computer Vision / Embedded / IoT roles -> prioritize 'Autonomous Robotics: Dual-Pipeline Visual Servoing & Odometry' (ROS 2, Arduino, Lucas-Kanade optical flow, HSV fire tracking) and 'Interactive Deep Learning Drawing Classifier' (TensorFlow/Keras custom CNN, 86.55% on QuickDraw).
      * For Backend / Java / Enterprise / OOP / Architecture / Database roles -> prioritize 'Enterprise Loan Management System' (Java SE, MVC, 5 GoF patterns, MySQL, Data Export & Reporting).
      * For Full-Stack / QA / Testing / CI/CD roles -> prioritize 'Personal Wealth Management Application' (React, Flask, SQLite, Cypress, Jest, pytest, Bandit, GitHub Actions CI/CD).
      * For Systems / OS / Kernel / C roles -> prioritize 'Mini-UnionFS' (C, FUSE 3, CoW, whiteouts).
   - BANNED PROJECTS: NEVER consider or include 'PC Parts E-Commerce Platform' or 'University Database Management System' under any circumstances.
   - FIRST BULLET EXPLAINS WHAT THE PROJECT DOES: For EVERY project on the resume, the FIRST bullet point MUST clearly state WHAT the project is and WHAT it does (its core product capability, user function, and problem solved). The remaining bullets should then detail the deep engineering architecture, database design, concurrency models, performance optimizations, and only authentic quantitative metrics from source materials.
   - For each selected project, write 3 to 4 detailed, highly technical bullet points demonstrating real engineering architecture, libraries, and design patterns from its verified documentation."""
    else:
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
      * Pillar 5 (Epistemic Multi-Agent Systems / Research / Clinical RAG / Graph Clustering): 'GLAS-Med: Evidence-Grounded Clinical Literature Synthesis' (GitHub: https://github.com/madhavofficial/evidence-grounded-clinical-literature-synthesis) — An advanced clinical and production microservice enhancement of the IEEE SPICES research paper adding PICO tuple projection, Oxford CEBM evidence hierarchy classification, 8-factor study reliability scoring, and 9-microservice deployment (FastAPI, MongoDB, Neo4j, FAISS, Docker) OR 'Multi-Modal AI Protein Analysis & Pathogenicity Reasoning Platform'
     - DEPTH, TECHNICAL SUBSTANCE & IMPACT RULES:
      * There is NO artificial 1-page restriction — prioritize technical substance, architectural depth, and quantitative metrics over arbitrary length limits. It is far more important that the reader understands the project than the size of the resume. For each project, write 3 to 4 comprehensive, punchy, high-density bullet points.
      * Bullet 1: MUST state WHAT the project is and WHAT it does (core product capability and problem solved).
       * Bullets 2-4: Detail deep technical architecture, libraries, concurrency/data flow, and performance optimizations. Include ONLY quantitative metrics that are explicitly documented in the candidate's base resume or portfolio. NEVER invent or hallucinate metrics, percentages, test counts, or benchmarks.
    - EXPANDED SKILLS: Ensure the Technical Skills section covers the full breadth of languages, frameworks, and tools across all included projects (e.g. Python, TypeScript, Java, C, Kotlin, Scala, PyTorch, Apache Kafka, Next.js, PostgreSQL, Docker, Android)."""
        else:
            print("-> Targeted role detected. Applying Deep Specialization Strategy...")
            project_strategy = """2. DYNAMIC PROJECT SELECTION & ALIGNMENT — TARGETED / SPECIALIZED JD STRATEGY:
   - Carefully review the Job Posting requirements (required languages, frameworks, domain, e.g. DevOps, TypeScript, Full-Stack Web, Backend, Distributed Systems, AI/ML, Data Science, Databases).
   - Compare the candidate's Current Resume Projects with the candidate's Verified GitHub Project Portfolio.
   - Select the 3 to 4 BEST-FITTING projects from the combined pool of projects (Current Resume + GitHub Portfolio).
   - REPLACE less relevant projects on the base resume with stronger-matching GitHub projects where appropriate:
      * For AI / RAG / Agent / NLP / Generative AI / Research / Machine Learning roles -> STRONGLY PRIORITIZE 'GLAS-Med: Evidence-Grounded Clinical Literature Synthesis' (GitHub: https://github.com/madhavofficial/evidence-grounded-clinical-literature-synthesis) as an advanced clinical & production engineering enhancement of the IEEE SPICES paper (featuring PICO extraction, Oxford CEBM evidence tiers, 8-factor reliability scoring, Neo4j knowledge graphs, and microservices), alongside 'Multi-Modal AI Protein Analysis & Pathogenicity Reasoning Platform'.
      * For DevOps / Cloud / Automation / Tooling roles -> prioritize 'job-hunter'.
      * For Big Data / Data Engineering / Streaming / Spark / Kafka / Distributed Systems / Batch Processing -> prioritize '153_Project3_BD' (Distributed Stream & Image Processing with Apache Kafka, Docker, Python) and 'Forecasting-Bike-Rental-Demand'.
      * For Full-Stack / TypeScript / FinTech / Database roles -> prioritize 'Ultimate-Trader-Dashboard' or 'University-DBMS-Management-'.
      * For Computer Vision / Deep Learning -> prioritize 'Sketch Recognition System'.
      * For Data Science / Regression / Analytics -> prioritize 'Forecasting-Bike-Rental-Demand'.
   - FIRST BULLET EXPLAINS WHAT THE PROJECT DOES: For EVERY project on the resume, the FIRST bullet point MUST clearly state WHAT the project is and WHAT it does (its core product capability, user function, and problem solved). The remaining bullets should then detail the deep engineering architecture, database design, concurrency models, performance optimizations, and only authentic quantitative metrics from source materials.
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
{profile.experience_instruction}
{project_strategy}
   - AUTONOMOUS AMBIGUITY EVALUATION: If the prompt marked this as targeted, but YOU evaluate from the Job Description that the role is actually broad, multi-track, general development centre (e.g. IDC), rotational, or lacks specific single-domain constraints, OVERRIDE and apply the AMBIGUOUS / BROAD JOB DIRECTIVE: include 4 to 5 diverse projects with 3-4 detailed, high-density bullets per project to showcase maximum engineering breadth.
{profile.flagship_instruction}
3. SKILLS SECTION: {profile.skills_instruction}
4. ZERO METRIC OR FACT FABRICATION & NO LENGTH RESTRICTIONS:
   - Do NOT invent non-existent projects, companies, durations, graduation date (May 2027), or credentials. Rely strictly on facts in the candidate's resume and project portfolio.
   - ABSOLUTE BAN ON FABRICATED NUMBERS & METRICS: ONLY cite quantitative metrics (percentages, accuracy, latency, scale, test coverage, counts) that appear verbatim in the candidate's base resume or portfolio. If a project or role does not have a metric in the source material, explain the engineering architecture and algorithms — NEVER invent numbers (e.g., do NOT invent '20% student proficiency', '30% event registrations', '95% coverage', '12 vulnerabilities', '200 TPS', 'AUC 0.92', etc.).
   - DO NOT invent unverified frameworks or integrations (e.g. do not invent SAP/ERP integrations or FastAPI if not present in the base resume or portfolio).
   - {profile.gpa_instruction} {profile.certifications_instruction}
   - There is NO artificial 1-page restriction - prioritize thorough understanding, architectural depth, and complete explanations over resume length. It is much more important that the reader understands the project than the size of the resume.
5. FORMATTING & TYPOGRAPHY:
   - Heavily utilize markdown bolding (**bold**) for all key metrics, numbers, core technologies, and frameworks across every bullet point.
   - GITHUB REPOSITORY LINKS RULE:
     * Under `## Selected Projects`, ONLY include a `*GitHub: <url>*` line beneath a project title IF that project has an explicit, verified GitHub repository URL in the candidate's Verified Project Portfolio below.
     * NEVER invent, guess, or fabricate GitHub URLs (e.g. NEVER use /Portfolio or guess repo names). If a project does not have a verified repository or its repository is None, DO NOT include a `*GitHub: ...*` line for it at all.
     * When a verified repository exists, place it on the line immediately beneath the title:
       `### Project Name (Core Technologies)`
       `*GitHub: https://github.com/...*`
   - CERTIFICATIONS POLICY:
     * {profile.certifications_instruction}
   - Output the COMPLETE tailored resume in clean, professional Markdown.

Candidate Base Resume:
{resume_text}

Candidate's Verified Project Portfolio:
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

        # 1. Primary: Groq Multi-Key & Model Cluster
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
                        timeout=60,
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

                    # Rate limits (TPM, RPM, TPD, 429) -> Key-specific quota, cycle to the next Groq key!
                    if any(term in err_str for term in ["rate_limit", "rate limit", "429", "limit_exceeded", "tokens per minute", "tpm", "tokens per day"]):
                        retries += 1
                        if retries < max_retries:
                            print(f"Rate/TPM limit hit on {active_model}. Cycling to next Groq key ({retries}/{max_retries})...")
                            client = config.cycle_groq_client()
                            continue
                        else:
                            print(f"-> All {max_retries} keys exhausted for {active_model}. Falling back to next model...")
                            break

                    # True single-request prompt size violation for this model architecture
                    if any(term in err_str for term in ["request too large", "413", "context_length_exceeded", "request_too_large"]):
                        print(f"Prompt exceeded context limit for {active_model}. Falling back to next model...")
                        break

                    print(f"Error on {active_model}: {e}. Falling back to next model...")
                    break
            if tailored_resume:
                break

        # 2. Fallback: OpenRouter (used only if Groq cluster failed or was exhausted)
        if not tailored_resume:
            print("Warning: Groq cluster exhausted. Falling back to OpenRouter...", file=sys.stderr)
            openrouter_key = os.getenv("OPENROUTER_API_KEY")
            if openrouter_key:
                from openai import OpenAI
                or_client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=openrouter_key, timeout=25)
                configured_openrouter_model = os.getenv("OPENROUTER_MODEL")
                openrouter_models = ([configured_openrouter_model] if configured_openrouter_model else list(PREFERRED_OPENROUTER_MODELS))
                for openrouter_model in openrouter_models:
                    try:
                        print(f"-> Trying OpenRouter fallback model: {openrouter_model}")
                        or_resp = or_client.chat.completions.create(
                            model=openrouter_model,
                            messages=[{"role": "user", "content": resume_prompt}],
                            temperature=0.2,
                            max_tokens=4096,
                            timeout=25,
                        )
                        if or_resp and or_resp.choices and or_resp.choices[0].message and or_resp.choices[0].message.content:
                            tailored_resume = or_resp.choices[0].message.content.strip()
                            break
                    except Exception as e:
                        print(f"Warning: OpenRouter fallback model {openrouter_model} failed: {e}", file=sys.stderr)

        if not tailored_resume:
            raise ValueError("Failed to generate tailored resume after trying Groq cluster and OpenRouter fallbacks.")

        if not getattr(profile, "include_certifications", False):
            tailored_resume = strip_certifications(tailored_resume)
        tailored_resume = ensure_selected_project_github_links(tailored_resume, portfolio, profile=profile)
        tailored_resume = ensure_career_objective_target(tailored_resume, company, title)
        tailored_resume = ensure_gpa(tailored_resume, profile=profile)
        tailored_resume = scrub_unverified_metrics(tailored_resume, profile_id=getattr(profile, "id", ""))
        
        # Save files in dedicated company directory with <profile.file_prefix>_ naming scheme
        clean_company = "".join([c for c in company if c.isalnum() or c in (' ', '_')]).replace(' ', '_')
        clean_title = "".join([c for c in title if c.isalnum() or c in (' ', '_')]).replace(' ', '_')
        clean_company = re.sub(r'_+', '_', clean_company).strip('_')
        clean_title = re.sub(r'_+', '_', clean_title).strip('_')

        company_dir = os.path.join(tailored_dir, clean_company)
        os.makedirs(company_dir, exist_ok=True)

        resume_filename = f"{profile.file_prefix}_{clean_company}_{clean_title}_Resume.md"
        resume_pdf_filename = f"{profile.file_prefix}_{clean_company}_{clean_title}_Resume.pdf"
        resume_tex_filename = f"{profile.file_prefix}_{clean_company}_{clean_title}_Resume.tex"

        resume_filepath = os.path.join(company_dir, resume_filename)
        resume_pdf_filepath = os.path.join(company_dir, resume_pdf_filename)
        resume_tex_filepath = os.path.join(company_dir, resume_tex_filename)

        with open(resume_filepath, "w", encoding="utf-8") as f:
            f.write(tailored_resume)

        # High-grade LaTeX / Tectonic compilation with automatic ReportLab fallback
        import latex_utils
        tex_content = latex_utils.markdown_to_latex(tailored_resume)
        with open(resume_tex_filepath, "w", encoding="utf-8") as f:
            f.write(tex_content)

        compiled_with_tectonic = latex_utils.compile_latex_to_pdf(tex_content, resume_pdf_filepath, resume_tex_filepath)
        if not compiled_with_tectonic:
            markdown_to_pdf(tailored_resume, resume_pdf_filepath, engine="reportlab")

        print(f"-> Tailored Resume saved to: {resume_filepath}")
        print(f"-> LaTeX Source saved to: {resume_tex_filepath}")
        print(f"-> ATS Resume PDF saved to: {resume_pdf_filepath}")
        
        # Store generated materials in database (only for default profile)
        if profile.id == "madhav":
            db.store_tailored_materials(job_id, resume_filepath, None, resume_pdf_filepath, None)
        
        return resume_filepath, resume_pdf_filepath
        
    except Exception as e:
        print(f"Error generating tailored materials: {e}", file=sys.stderr)
        return None

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Tailor application materials for a job listing")
    parser.add_argument("job_id", help="Job ID or URL to tailor for")
    parser.add_argument("--profile", "-p", default="madhav", help="Candidate profile (e.g. 'madhav', 'mahika')")
    args = parser.parse_args()
    tailor_materials(args.job_id, profile_name=args.profile)
