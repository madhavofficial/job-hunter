"""Multi-Profile Configuration and Management for Job Hunter Resume Builder.

Supports profile switching between candidate profiles (e.g. Madhav Jayam, Mahika Neranjen)
while preserving 100% backward compatibility for the default profile.
"""

from dataclasses import dataclass, field
import os
import sys
from typing import Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


@dataclass
class Profile:
    id: str
    name: str
    first_name: str
    last_name: str
    file_prefix: str
    email: str
    phone: str
    linkedin: str
    github_user: str
    github_url: str
    resume_path: str
    include_gpa: bool
    gpa_text: Optional[str]
    gpa_instruction: str
    experience_instruction: str
    flagship_instruction: str
    skills_instruction: str
    include_certifications: bool = False
    certifications_instruction: str = "Do NOT include a Certifications section on the resume."
    known_project_urls: Dict[str, str] = field(default_factory=dict)
    curated_projects: Dict[str, dict] = field(default_factory=dict)


# Default candidate: Madhav Jayam
MADHAV_KNOWN_PROJECT_URLS = {
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
    "unionfs": "https://github.com/madhavofficial/mini-unionfs",
    "mini-unionfs": "https://github.com/madhavofficial/mini-unionfs",
    "mini_unionfs": "https://github.com/madhavofficial/mini-unionfs",
    "fuse": "https://github.com/madhavofficial/mini-unionfs",
    "pesuacademy": "https://github.com/madhavofficial/pesuacademy-mcp",
    "pesuacademy-mcp": "https://github.com/madhavofficial/pesuacademy-mcp",
    "pesu": "https://github.com/madhavofficial/pesuacademy-mcp",
    "mcp": "https://github.com/madhavofficial/pesuacademy-mcp",
}

MADHAV_CURATED_PROJECTS = {
    "neuro_capstone": {
        "display_name": "Multi-Modal AI Protein Analysis & Pathogenicity Reasoning Platform",
        "description": "Architected an end-to-end clinical AI platform predicting neurodegenerative mutation pathogenicity by fusing 3D AlphaFold structures, evolutionary biophysics, and biomedical literature. Full-stack React 18, TypeScript, Vite, Tailwind CSS web application with an interactive 3D molecular protein viewer (PDB rendering) and diagnostic verdict dashboards backed by FastAPI. 3D structural biophysics pipeline in BioPython (ShrakeRupley SASA, DSSP secondary structure, steric clash detection, salt bridge/H-bond analysis) using virtual residue swapping against AlphaFold and ESMFold models. Dual-RAG retrieval engine indexing PubMed/Europe PMC literature into FAISS via SBERT embeddings to ground LLM clinical reasoning (Llama 3.3, Qwen 235B) in peer-reviewed evidence (72% top-5 relevance). Relational data layer in Supabase (PostgreSQL) with Row-Level Security (RLS) and index-optimized variant caching; 144-run ablation benchmarking harness achieving 98.6% completion and 100% JSON schema validity against ClinVar ground truth.",
        "topics": ["bioinformatics", "alphafold", "biopython", "fastapi", "react", "typescript", "supabase", "faiss", "rag", "clinvar", "python"],
        "url": "https://github.com/madhavofficial/neuro_capstone",
    },
    "evidence-grounded-clinical-literature-synthesis": {
        "display_name": "GLAS-Med: Evidence-Grounded Clinical Literature Synthesis",
        "description": "Iterative clinical and production improvement on the IEEE SPICES publication project architecture. Developed a micro-service-based multi-agent system that ingests 300-800 scholarly articles per query, extracts PICO elements, and generates evidence-ranked clinical summaries. Orchestrated 9 Docker containers with FastAPI, Neo4j knowledge graph, and FAISS vector store; achieved 92.7% accuracy and 89.8% F1 on benchmark synthesis tasks, outperforming baseline LLMs by +14% F1.",
        "topics": ["clinical-nlp", "evidence-based-medicine", "knowledge-graphs", "pico-extraction", "oxford-cebm", "multi-agent", "python", "bioinformatics", "fastapi", "docker", "neo4j", "mongodb", "faiss"],
        "url": "https://github.com/madhavofficial/evidence-grounded-clinical-literature-synthesis",
    },
    "153_Project3_BD": {
        "display_name": "Distributed High-Throughput Stream & Image Processing Pipeline with Apache Kafka",
        "description": "Distributed real-time stream processing architecture utilizing Apache Kafka, Zookeeper, Docker, Python, and OpenCV. High-throughput producers streaming image and numerical sensor data over partitioned Kafka topics with configurable batching and replication. Multi-worker consumer groups executing edge image processing, feature extraction, and anomaly detection under low-latency constraints. Pipeline health monitoring, lag tracking, and fault tolerance across broker failure scenarios.",
        "topics": ["kafka", "apache-kafka", "distributed-systems", "docker", "python", "opencv", "stream-processing", "flask"],
        "url": "https://github.com/varunnhn/153_Project3_BD",
    },
    "Drawing-A-New-Way-To-Search-ML-": {
        "display_name": "Sketch Recognition System",
        "description": "Interactive deep learning web application classifying freehand sketches across 50 ambiguous object classes from Google QuickDraw. Deep hierarchical CNN in PyTorch integrating custom residual blocks and Squeeze-and-Excitation (SE) channel attention mechanisms achieving 86% test accuracy. Multi-worker data pipeline with pinned-memory optimization streaming 500,000 samples out-of-core, reducing per-epoch training time by over 30%. Custom batch augmentations with Mixup image blending (alpha=0.2), Cutout block masking, and label smoothing regularization. Flask inference API and JavaScript frontend.",
        "topics": ["pytorch", "cnn", "deep-learning", "computer-vision", "quickdraw", "flask", "python"],
        "url": "https://github.com/madhavofficial/Drawing-A-New-Way-To-Search-ML-",
    },
    "CareerTime": {
        "display_name": "CareerTime - AI Career Intelligence Platform",
        "description": "AI-powered career advisor platform delivering real-time hiring intelligence, market compensation trends, and role roadmaps grounded in live web search data. Low-latency inference using Groq LPU acceleration and LangChain orchestration with dynamic prompt routing and intent classification. Automated web citation extraction and Markdown parsing producing inline clickable references without hallucinations. Streamlit dark UI featuring inline message editing, real-time prompt resubmission, and persistent multi-session JSON history.",
        "topics": ["streamlit", "langchain", "groq", "lpu", "duckduckgo-search", "career-advisor", "rag", "python"],
        "url": "https://github.com/madhavofficial/CareerTime",
    },
    "job-hunter": {
        "display_name": "Autonomous Job Discovery, Career Intelligence & Application Automation Engine",
        "description": "Autonomous career intelligence and application workflow engine integrating multi-source job discovery, heuristic semantic matching, and automated resume tailoring. Multi-profile architectural separation supporting concurrent candidate profiles with role-specific constraints, GPA policies, and typography guardrails. Automated Tectonic LaTeX compilation pipeline with orphan prevention, ATS-compliant ASCII hygiene, and dual 1-page/2-page compilation workflows. Interactive Flask/HTML web dashboard with SQLite persistence for real-time application tracking.",
        "topics": ["python", "automation", "sqlite", "latex", "tectonic", "flask", "groq", "playwright"],
        "url": "https://github.com/madhavofficial/job-hunter",
    },
    "Ultimate-Trader-Dashboard-GitHub-Repository-Structure": {
        "display_name": "Smart Market Watchlist & Real-Time Trading Terminal",
        "description": "Full-stack real-time financial market analytics terminal and watchlist tracker built with TypeScript, Next.js, and Tailwind CSS. WebSocket streaming client for live market tick feeds, dynamic order book depth visualization, and real-time portfolio P&L calculation. Relational data schemas in PostgreSQL with Prisma ORM for persistent watchlist curation, user alerts, and historical trade logging. Containerized services using Docker Compose.",
        "topics": ["fintech", "nextjs", "typescript", "prisma", "postgresql", "websockets", "trading-terminal", "docker"],
        "url": "https://github.com/madhavofficial/Ultimate-Trader-Dashboard-GitHub-Repository-Structure",
    },
    "Forecasting-Bike-Rental-Demand": {
        "display_name": "Hourly Bike-Sharing Demand Forecasting & Time-Series Regression Pipeline",
        "description": "End-to-end time-series regression and demand forecasting pipeline predicting hourly municipal bike-sharing rental counts from meteorological and seasonal variables. Exploratory data analysis, cyclical feature engineering (hour-of-day sine/cosine encoding, workday/holiday interaction), and collinearity analysis across weather indicators. Trained and benchmarked multiple regression models (Random Forest, Gradient Boosting, Ridge, Lasso) evaluated via RMSE and R-squared metrics. Automated training and evaluation pipeline with cross-validation and hyperparameter tuning via GridSearch.",
        "topics": ["machine-learning", "scikit-learn", "time-series", "regression", "feature-engineering", "random-forest", "python"],
        "url": "https://github.com/madhavofficial/Forecasting-Bike-Rental-Demand",
    },
    "mini-unionfs": {
        "display_name": "Mini-UnionFS: Layered Union File System in C with FUSE",
        "description": "Lightweight user-space layered union file system in C using FUSE 3 (repo: madhavofficial/mini-unionfs). Core features: (1) Transparent multi-branch merging of read-only lower directory and read-write upper directory; (2) Block-by-block POSIX Copy-on-Write (CoW) preserving base filesystem immutability; (3) Whiteout markers (.wh.<filename>) and opaque directory masking (.wh.<dirname>) for file and directory deletions; (4) POSIX-compliant VFS operations; (5) Automated bash test harness validating layer visibility, CoW isolation, and opaque directory deletions.",
        "topics": ["c", "fuse", "filesystems", "operating-systems", "posix", "systems-programming", "copy-on-write", "whiteouts"],
        "url": "https://github.com/madhavofficial/mini-unionfs",
    },
    "pesuacademy-mcp": {
        "display_name": "PESU Academy MCP Server: Model Context Protocol Tool Suite",
        "description": "Architected an open-source Model Context Protocol (MCP) server in TypeScript/Node.js exposing 26 tools over stdio for AI agent integration with university academic portals. Engineered automated session authentication, persistent cookie jar state, and automatic retry interceptors with Cheerio DOM parsing and in-memory PDF text extraction. Designed cross-platform path resolution and Windows filename sanitization; developed an automated test suite achieving 96 passing unit and end-to-end protocol integration tests.",
        "topics": ["mcp", "model-context-protocol", "typescript", "nodejs", "agents", "automation", "cheerio", "developer-tools"],
        "url": "https://github.com/madhavofficial/pesuacademy-mcp",
    },
}

MADHAV_PROFILE = Profile(
    id="madhav",
    name="Madhav Jayam",
    first_name="Madhav",
    last_name="Jayam",
    file_prefix="Madhav_Jayam",
    email="madhavjayam@gmail.com",
    phone="+91-709-343-8234",
    linkedin="http://www.linkedin.com/in/madhav-jayam-032311282",
    github_user="madhavofficial",
    github_url="https://github.com/madhavofficial",
    resume_path=os.path.join(BASE_DIR, "resume.md"),
    include_gpa=False,
    gpa_text=None,
    gpa_instruction="Do NOT include GPA on the resume.",
    include_certifications=False,
    certifications_instruction="CRITICAL: Do NOT include any 'Certifications', 'Courses', or 'Licenses' section on the resume under any circumstances.",
    experience_instruction="""1. PROFESSIONAL EXPERIENCE (STRICT 1-PAGE BUDGET):
   - Qualcomm India Pvt. Ltd.: Condense into EXACTLY 3 high-impact bullets (autonomous Jira agent + Claude Code Skills + MCP, deterministic routing + pre-validated Splunk queries, Pydantic validation guardrails + 8,700 analyzed tickets). DO NOT output more than 3 bullets.
   - O.C. Tanner India Pvt. Ltd.: Condense into EXACTLY 2 bullets (50+ Jira tickets for Kotlin accessibility API, 10% to 70% automated test coverage across Scala/Android).
   - DO NOT remove Career Objective — keep it targeted to the company and role.
   - ZERO HARDWARE / NON-CS FABRICATION: Candidate is strictly a Computer Science and Engineering (CSE) student. NEVER claim expertise, grounding, or career interest in hardware board design, electronic circuits, analogue/digital circuits, PCB layout, or FPGA development. For telecom or hardware companies, frame contributions strictly around low-level C/C++, Linux systems programming, embedded firmware, networking stacks, and data processing.""",
    flagship_instruction="""2.5. PUBLICATIONS & PROJECTS DEDUPLICATION (STRICT 1-PAGE BUDGET):
   - Under '## Publications', include the IEEE SPICES paper with EXACTLY 2 bullets:
     * **Conference Acceptance**: Selected for **IEEE SPICES**; DOI: [10.5281/zenodo.22676649](https://doi.org/10.5281/zenodo.22676649) | GitHub: [GenAI-Scientific-Literature-System](https://github.com/GenAI-Scientific-Literature-System/GenAI-Scientific-Literature-System-multi-agent-system).
     * Built an evidence-grounded multi-agent system querying arXiv, PubMed, and Semantic Scholar (300-800 papers) with Louvain graph clustering and 5-agent ensemble, demonstrating 92.7% accuracy and 89.8% F1 score across benchmarks.
   - DO NOT write more than 2 bullets for Publications.
   - CRITICAL ANTI-DUPLICATION RULE:
     * 'GLAS-Med: Evidence-Grounded Clinical Literature Synthesis' and 'Multi-Agent Generative AI System for Scientific Literature Analysis' (the IEEE SPICES paper) are the SAME underlying scientific literature synthesis system.
     * The IEEE SPICES paper belongs STRICTLY under '## Publications'.
     * NEVER list 'Multi-Agent Generative AI System for Scientific Literature Analysis' under '## Selected Projects'!
     * NEVER list both 'GLAS-Med' and 'Multi-Agent Generative AI System' as two separate projects under '## Selected Projects' on the same resume! Doing so is a blatant duplicate of the same system.
     * In '## Selected Projects', if featuring 'GLAS-Med', pair it with distinct systems such as 'Multi-Modal AI Protein Analysis & Pathogenicity Reasoning Platform' (neuro_capstone) and 'Autonomous Job Discovery, Career Intelligence & Application Automation Engine' (job-hunter), 'Mini-UnionFS: Layered Union File System in C with FUSE' (mini-unionfs), or 'Distributed High-Throughput Stream & Image Processing Pipeline with Apache Kafka' (153_Project3_BD).""",

    skills_instruction="Update the Technical Skills section to highlight the exact languages and tools used across the selected projects and experience (e.g., add TypeScript, Docker, Prisma, Kafka, etc. if featuring those projects).",
    known_project_urls=MADHAV_KNOWN_PROJECT_URLS,
    curated_projects=MADHAV_CURATED_PROJECTS,
)


SECONDARY_KNOWN_PROJECT_URLS = {
    "capstone": "https://github.com/madhavofficial/neuro_capstone",
    "neuro": "https://github.com/madhavofficial/neuro_capstone",
    "pathogenicity": "https://github.com/madhavofficial/neuro_capstone",
    "protein": "https://github.com/madhavofficial/neuro_capstone",
    "neurodegenerative": "https://github.com/madhavofficial/neuro_capstone",
    "resume": "https://github.com/Mahika6/genai-project",
    "matcher": "https://github.com/Mahika6/genai-project",
    "ats": "https://github.com/Mahika6/genai-project",
    "semantic": "https://github.com/Mahika6/genai-project",
    "genai": "https://github.com/Mahika6/genai-project",
    "loan": "https://github.com/surabhi1828/LoanManagementSystem",
    "lms": "https://github.com/surabhi1828/LoanManagementSystem",
    "ooad": "https://github.com/surabhi1828/LoanManagementSystem",
    "mvc": "https://github.com/surabhi1828/LoanManagementSystem",
    "drawing": "https://github.com/madhavofficial/Drawing-A-New-Way-To-Search-ML-",
    "sketch": "https://github.com/madhavofficial/Drawing-A-New-Way-To-Search-ML-",
    "classifier": "https://github.com/madhavofficial/Drawing-A-New-Way-To-Search-ML-",
    "quickdraw": "https://github.com/madhavofficial/Drawing-A-New-Way-To-Search-ML-",
    "wealth": "https://github.com/Mahika6/PESU_RR_CSE_F_P06_Personal_Wealth_Management_Software_Quadra-Minds",
    "quadra": "https://github.com/Mahika6/PESU_RR_CSE_F_P06_Personal_Wealth_Management_Software_Quadra-Minds",
    "quadraminds": "https://github.com/Mahika6/PESU_RR_CSE_F_P06_Personal_Wealth_Management_Software_Quadra-Minds",
    "odometry": "https://github.com/surabhi1828/autonomous-detection-4wd-robot",
    "robotics": "https://github.com/surabhi1828/autonomous-detection-4wd-robot",
    "robot": "https://github.com/surabhi1828/autonomous-detection-4wd-robot",
    "fire": "https://github.com/surabhi1828/autonomous-detection-4wd-robot",
    "visual": "https://github.com/surabhi1828/autonomous-detection-4wd-robot",
    "unionfs": "https://github.com/Mahika6/mini-unionfs",
    "mini-unionfs": "https://github.com/Mahika6/mini-unionfs",
    "mini_unionfs": "https://github.com/Mahika6/mini-unionfs",
    "fuse": "https://github.com/Mahika6/mini-unionfs",
}

SECONDARY_CURATED_PROJECTS = {
    "neuro_capstone": {
        "display_name": "Multi-Modal AI Protein Analysis & Pathogenicity Reasoning Platform",
        "description": "End-to-end clinical AI and diagnostics platform predicting neurodegenerative mutation pathogenicity by fusing 3D AlphaFold structures, evolutionary biophysics, and biomedical literature (team repo: madhavofficial/neuro_capstone). Core features: (1) Full-stack React 18, TypeScript, Vite, and Tailwind CSS web application with an interactive 3D molecular protein viewer (PDB rendering) and diagnostic verdict dashboards backed by FastAPI; (2) 3D structural biophysics pipeline in BioPython (ShrakeRupley SASA, DSSP secondary structure, steric clash detection, salt bridge/H-bond analysis) using virtual residue swapping against AlphaFold and ESMFold models; (3) Dual-RAG retrieval engine indexing PubMed/Europe PMC literature into FAISS via SBERT embeddings to ground LLM clinical reasoning (Llama 3.3, Qwen 235B) in peer-reviewed evidence (72% top-5 relevance); (4) Relational data layer in Supabase (PostgreSQL) with Row-Level Security (RLS) and index-optimized variant caching; (5) 144-run ablation benchmarking harness achieving 98.6% completion and 100% JSON schema validity against ClinVar ground truth.",
        "topics": ["bioinformatics", "alphafold", "biopython", "fastapi", "react", "typescript", "supabase", "faiss", "rag", "clinvar", "python", "full-stack", "web", "database", "postgresql"],
        "url": "https://github.com/madhavofficial/neuro_capstone"
    },
    "Resume-JD-Semantic-Matcher": {
        "display_name": "ATS Resume-JD Semantic Matcher & Explainable Screening Engine",
        "description": "ATS-style candidate-job matching platform using a 5-agent ML & GenAI pipeline (repo: Mahika6/genai-project). Core features: (1) 5-agent architecture: Parsing -> Skill Normalization (RAG with FAISS) -> Semantic Matching (SBERT + XGBoost) -> Gap Analysis -> Explanations; (2) Dual ML models: XGBoost Classifier (3-class: Reject, Maybe, Shortlist) and XGBoost Regressor trained on 7,751 clean pairs; (3) FAISS vector store indexing 2,831 unique technical skills via SBERT (all-MiniLM-L6-v2); (4) Generative AI natural language explanations using Hugging Face FLAN-T5-small; (5) SHAP TreeExplainer feature importance and Streamlit interactive dashboard.",
        "topics": ["xgboost", "sbert", "faiss", "flan-t5", "shap", "streamlit", "nlp", "python"],
        "url": "https://github.com/Mahika6/genai-project"
    },
    "LoanManagementSystem": {
        "display_name": "Enterprise Loan Management System (Java MVC & 5 OOP Design Patterns)",
        "description": "Role-based Loan Management System built with Java SE, MVC architecture, and MySQL (team collaboration: surabhi1828/LoanManagementSystem). Core contributions: (1) Owned Data Export & System Reporting (automated generation of formatted loan histories in CSV/HTML for auditing); (2) User Role Management (administrative oversight tools for adding internal staff and fetching system statistics); (3) System-wide 5 GoF design patterns (Chain of Responsibility for hierarchical approval limits, Decorator for runtime EMI add-ons, Observer for status alerts, Factory Method for user instantiation, Singleton for database persistence); (4) JDBC transaction integrity and RBAC.",
        "topics": ["java", "mvc", "mysql", "design-patterns", "solid-principles", "fintech", "banking"],
        "url": "https://github.com/surabhi1828/LoanManagementSystem"
    },
    "Interactive-Drawing-Classifier": {
        "display_name": "Interactive Deep Learning Freehand Sketch Classifier (Google QuickDraw)",
        "description": "Hand-drawn doodle classification system evaluating multiple machine learning architectures on Google's QuickDraw dataset across 50 categories (team repo: madhavofficial/Drawing-A-New-Way-To-Search-ML-). Core features: (1) Progressive CNN architecture optimization (v1-v4) achieving 86.55% accuracy on QuickDraw bitmap data; (2) Multi-model benchmark suite evaluating custom CNNs against Logistic Regression baselines, multi-kernel SVMs (Linear, RBF, Polynomial, Sigmoid), and Transfer Learning models (MobileNet, ResNet50, Inception v3); (3) Optimized NumPy data preprocessing pipeline with binarization and pixel normalization.",
        "topics": ["tensorflow", "scikit-learn", "cnn", "svm", "quickdraw", "computer-vision", "python"],
        "url": "https://github.com/madhavofficial/Drawing-A-New-Way-To-Search-ML-"
    },
    "Personal-Wealth-Management": {
        "display_name": "Full-Stack Personal Wealth Management & Financial Analytics Platform",
        "description": "Full-stack personal wealth management platform built with React, Flask, and SQLite (team repo: Mahika6/PESU_RR_CSE_F_P06_Personal_Wealth_Management_Software_Quadra-Minds). Core features: (1) Expense tracking, portfolio monitoring, budgeting, and goal planning; (2) Multi-tier automated testing: Cypress for end-to-end user workflows, Jest for React component testing, and pytest/pytest-cov for backend APIs; (3) Automated security and vulnerability scanning using Bandit, pip-audit, and npm audit; (4) GitHub Actions multi-stage CI/CD pipelines enforcing >=75% code coverage quality gates, linting (flake8, ESLint), and automated packaging.",
        "topics": ["react", "flask", "sqlite", "cypress", "jest", "pytest", "bandit", "ci-cd", "github-actions", "python"],
        "url": "https://github.com/Mahika6/PESU_RR_CSE_F_P06_Personal_Wealth_Management_Software_Quadra-Minds"
    },
    "Visual-Odometry-Fire-Detection": {
        "display_name": "Autonomous Robotics: Dual-Pipeline Visual Servoing & Monocular Odometry",
        "description": "Autonomous 4-WD differential-drive mobile robotics system built with ROS 2 and Arduino (Mobile Autonomous Robots course at PES University; team repo: surabhi1828/autonomous-detection-4wd-robot; team: Surabhi Venkatesha, Mahika Neranjen, Brinda S, B M Krupa). Core features: (1) Dual-pipeline processing on monocular IP camera stream over Wi-Fi bridge; (2) Reactive visual servoing tracking targets via HSV color-space masking to issue steering commands; (3) Visual odometry utilizing Lucas-Kanade sparse optical flow to estimate spatial trajectory; (4) Arduino C++ firmware (PWM motor driver, 1000ms safety deadman switch); (5) Live RViz2 trajectory visualization (/robot_path) and cali_flame.py diagnostic GUI.",
        "topics": ["ros2", "robotics", "opencv", "arduino", "rviz2", "optical-flow", "python"],
        "url": "https://github.com/surabhi1828/autonomous-detection-4wd-robot"
    },
    "Mini-UnionFS": {
        "display_name": "Mini-UnionFS: Layered Union File System in C with FUSE",
        "description": "Lightweight user-space layered union file system in C using FUSE 3 (repo: Mahika6/mini-unionfs). Core features: (1) Transparent multi-branch merging of read-only lower directory and read-write upper directory; (2) Block-by-block POSIX Copy-on-Write (CoW) preserving base filesystem immutability; (3) Whiteout markers (.wh.<filename>) and opaque directory masking (.wh.<dirname>) for file and directory deletions; (4) POSIX-compliant VFS operations; (5) Automated bash test harness validating layer visibility, CoW isolation, and opaque directory deletions.",
        "topics": ["c", "fuse", "file-systems", "linux", "kernel", "systems-programming"],
        "url": "https://github.com/Mahika6/mini-unionfs"
    }
}

SECONDARY_PROFILE = Profile(
    id="mahika",
    name="Mahika Neranjen",
    first_name="Mahika",
    last_name="Neranjen",
    file_prefix="Mahika_Neranjen",
    email="mahikaneranjen@gmail.com",
    phone=os.getenv("SECONDARY_PHONE", os.getenv("MAHIKA_PHONE", "+91-XXXXXXXXXX")),
    linkedin="http://linkedin.com/in/mahika-neranjen-81755b275",
    github_user="Mahika6",
    github_url="https://github.com/Mahika6",
    resume_path=os.path.join(BASE_DIR, "profiles", "mahika", "resume.md"),
    include_gpa=True,
    gpa_text="CGPA: 8.06 (Sem 6) | Distinction Scholarship (Semesters 1, 3, 4, 5, 6)",
    gpa_instruction="ALWAYS INCLUDE the candidate's exact CGPA: 'CGPA: 8.06 (Sem 6) | Distinction Scholarship (Semesters 1, 3, 4, 5, 6)' under the Education section.",
    include_certifications=False,
    certifications_instruction="CRITICAL: Do NOT include any 'Certifications', 'Courses', or 'Licenses' section on the resume. The candidate explicitly does not share certifications.",
    experience_instruction="""1. PROFESSIONAL EXPERIENCE & LEADERSHIP:
   - Preserve the candidate's core professional, teaching, and research experiences with all technical depth and hard metrics:
     * **Research Intern - AI-Based Radar Emitter Identification | DRDO (Electronic Warfare Division)** (Summer 2026): Detail the end-to-end AI pipeline for unknown radar emitter identification, geometry-based PDW simulator modeling 150 concurrent emitters, generation of 63,395 TOA-sorted PDWs, signal deinterleaving with PRI and RF clustering, LSTM sequence classifier (**94.2% accuracy**, **95.1% Precision**, **94.2% Recall**, **94.2% F1 score**), and rule-based ECM recommendation decision layer (Spot Jamming, DRFM Deception, Barrage Jamming).
     * **Teaching Assistant - Python Programming Lab | PES University** (Sem 5): Selected by faculty to assist Python lab instruction for first-year Bachelor of Technology students; acted as primary contact for debugging support, algorithms, and syntax clarification; conducted viva examinations, evaluated lab assignments, and provided structured feedback strengthening foundational programming concepts. (CRITICAL: Do NOT invent arbitrary percentages or metrics like "20% improvement").
     * **Head of Social Media & Content | The Amateur Manager and Scientist (TAMS)**: Led content strategy and social media presence for PES University inter-college technical events, driving participant outreach and event engagement. (CRITICAL: Do NOT invent arbitrary percentages like "30% increase in registrations").
    - ZERO METRIC FABRICATION: Rely strictly on numbers present in the base resume. Never fabricate statistics, coverage percentages, or performance multipliers.
    - ZERO HARDWARE / NON-CS FABRICATION: The candidate is strictly a Computer Science and Engineering (CSE) undergraduate. NEVER claim grounding, training, or career interest in electronic circuits, digital/analogue circuit design, PCB layout, high-speed board design, VLSI, or FPGA development in the Career Objective, Technical Skills, or any bullet points. For hardware or telecom companies (such as Tejas Networks), position the candidate strictly as an Embedded Software, C/C++, Linux Systems Programming, and Firmware engineer.
    - CAREER OBJECTIVE: In `## Career Objective`, NEVER mention or include 'robotics' or 'hardware engineering / FPGA'.
    - LONG FORMS RULE: Use long forms ONLY for these specific terms (do not expand other acronyms):
      * Use 'Database management systems' instead of 'DBMS'.
      * Use 'Generative AI and applications' instead of 'Generative AI' ONLY under Relevant Coursework.
      * Use 'Bachelor of Technology' instead of 'B.Tech' or 'B Tech'.
    - PURE ASCII ENCODING RULE (NO MOJIBAKE): NEVER use unicode em-dashes, arrows, or (>=). Always use standard ASCII: hyphen (-), arrow (->), and (>=) to prevent ATS mojibake.
    - BANNED PROJECTS: NEVER consider or include 'PC Parts E-Commerce Platform' or 'University Database Management System' under any circumstances.""",
    flagship_instruction="""2.5. FLAGSHIP CAPSTONE & RESEARCH PROJECTS:
   - CRITICAL SEPARATION OF INTERNSHIP VS PROJECTS: The candidate's work at DRDO (AI-Based Radar Emitter Identification & ECM Recommendation Engine) is strictly HER PROFESSIONAL RESEARCH INTERNSHIP under `## Professional Experience`. DO NOT list, duplicate, or include DRDO or radar emitter identification as a project under `## Selected Projects`.
   - NEVER consider or include 'PC Parts E-Commerce Platform' or 'University Database Management System'.
   - CORE FLAGSHIP PRINCIPLE: 'Multi-Modal AI Protein Analysis & Pathogenicity Reasoning Platform' (React 18, TypeScript, Vite, Tailwind CSS, 3D molecular viewer, FastAPI, Supabase PostgreSQL with RLS, 144-run ablation benchmarking harness against ClinVar ground truth; team repo: madhavofficial/neuro_capstone) is the candidate's primary technical flagship demonstrating modern full-stack web engineering, backend API architecture, and relational database systems. STRONGLY PRIORITIZE including it across all AI/ML, Full-Stack, Web, TypeScript, React, Database, and general Software Engineering / IT Developer roles.
   - ANTI-CLUSTERING RULE: NEVER select both 'Enterprise Loan Management System' and 'Personal Wealth Management Application' on the same resume! Doing so causes redundant domain clustering in finance. Choose at most one finance-specific project and pair it with a system of different architectural breadth (specifically 'neuro_capstone').
   - Prominently feature the candidate's flagship academic and engineering projects in `## Selected Projects`:
     * **Multi-Modal AI Protein Analysis & Pathogenicity Reasoning Platform** (React 18, TypeScript, Vite, Tailwind CSS, 3D molecular viewer, FastAPI, AlphaFold 3D PDB structures, BioPython ShrakeRupley SASA, DSSP secondary structure, steric clash analysis, Dual-RAG with FAISS/SBERT, Supabase PostgreSQL with RLS, 144-run ablation benchmarking harness against ClinVar ground truth; team repo: madhavofficial/neuro_capstone).
     * **Resume-JD Semantic Matcher** (5-agent architecture: Parsing -> FAISS RAG Skill Normalization -> SBERT + XGBoost Semantic Matching -> Gap Analysis -> SHAP + FLAN-T5-small natural language explanations; trained on 7,751 pairs, 2,831 skills in FAISS; repo: Mahika6/genai-project).
     * **Enterprise Loan Management System** (Java SE, MVC architecture, MySQL, 5 GoF design patterns: Chain of Responsibility, Decorator, Observer, Factory Method, Singleton; Data Export & System Reporting and User Role Management; team repo: surabhi1828/LoanManagementSystem).
     * **Interactive Deep Learning Drawing Classifier** (Google QuickDraw dataset across 50 categories; progressive custom CNN architecture reaching 86.55% accuracy; benchmarked against Logistic Regression, multi-kernel SVMs, and transfer learning models MobileNet/ResNet50; team repo: madhavofficial/Drawing-A-New-Way-To-Search-ML-).
     * **Personal Wealth Management Application** (React, Flask, SQLite; multi-tier testing with Cypress E2E, Jest, and pytest/pytest-cov; security scanning with Bandit, pip-audit, and npm audit; GitHub Actions CI/CD enforcing >=75% code coverage; repo: Mahika6/PESU_RR_CSE_F_P06_Personal_Wealth_Management_Software_Quadra-Minds).
     * **Autonomous Robotics: Dual-Pipeline Visual Servoing & Odometry** (ROS 2, Arduino, monocular IP camera, Lucas-Kanade optical flow visual odometry, HSV fire tracking visual servoing, RViz2 telemetry; team repo: surabhi1828/autonomous-detection-4wd-robot).
     * **Mini-UnionFS: Layered Union File System in C with FUSE** (C, FUSE 3, layered directory merging, Copy-on-Write, whiteouts, opaque directory deletion, automated bash test harness; repo: Mahika6/mini-unionfs).""",
    skills_instruction="Update the Technical Skills section to highlight the exact languages, frameworks, and tools used across the selected projects and experience (e.g. Python, Java, C, JavaScript, SQL, HTML/CSS, PyTorch, TensorFlow, Scikit-learn, XGBoost, SBERT, FAISS, FLAN-T5, SHAP, BioPython, AlphaFold, ROS2, OpenCV, Arduino, FUSE, React, Flask, SQLite, MySQL, Cypress, Jest, pytest, Bandit, GitHub Actions CI/CD).",
    known_project_urls=SECONDARY_KNOWN_PROJECT_URLS,
    curated_projects=SECONDARY_CURATED_PROJECTS,
)

# Alias for backward compatibility
MAHIKA_PROFILE = SECONDARY_PROFILE

PROFILES: Dict[str, Profile] = {
    "madhav": MADHAV_PROFILE,
    "secondary": SECONDARY_PROFILE,
    "partner": SECONDARY_PROFILE,
    "mahika": SECONDARY_PROFILE,
}


def get_profile(profile_id: Optional[str] = None) -> Profile:
    """Get candidate profile by id or name. Defaults to 'madhav' if unspecified."""
    if not profile_id:
        return MADHAV_PROFILE
    key = str(profile_id).strip().lower()
    if key in ("secondary", "partner", "mahika") or "mahika" in key:
        return SECONDARY_PROFILE
    return PROFILES.get(key, MADHAV_PROFILE)


def list_profiles() -> List[dict]:
    """Return list of available profiles for UI dropdowns."""
    seen_ids = set()
    result = []
    for p in [MADHAV_PROFILE, SECONDARY_PROFILE]:
        if p.id not in seen_ids:
            seen_ids.add(p.id)
            result.append({
                "id": p.id,
                "name": p.name,
                "file_prefix": p.file_prefix,
                "github_user": p.github_user,
                "include_gpa": p.include_gpa,
                "gpa_text": p.gpa_text,
            })
    return result
