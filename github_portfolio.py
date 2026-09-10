"""GitHub Portfolio & Codebase Intelligence Integrator.

Performs deep repository inspection (reading file trees, dependency manifests,
database schemas, Docker/CI configurations, and full READMEs) across local workspaces
and remote GitHub repositories to generate factual, concrete project descriptions.
"""

import base64
import json
import os
import re
import subprocess
import sys
import time
import requests
from dotenv import load_dotenv

load_dotenv()

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".github_portfolio_cache.json")
CACHE_TTL_SECONDS = 86400  # 24 hours
USER_HOME = os.path.expanduser("~")

# In-progress, incomplete, or forked projects to exclude from active resumes
EXCLUDED_REPOSITORIES = {
    "secure-devops-scanner",
    "securedevopsscanner",
    "quadra_robo",
    "quadrarobo",
    "mar_quadrupled_robo",
    "hyperdog",
}

FEATURED_EXTERNAL_REPOSITORIES = [
    {
        "owner": "GenAI-Scientific-Literature-System",
        "name": "GenAI-Scientific-Literature-System-multi-agent-system",
        "full_name": "GenAI-Scientific-Literature-System/GenAI-Scientific-Literature-System-multi-agent-system",
        "url": "https://github.com/GenAI-Scientific-Literature-System/GenAI-Scientific-Literature-System-multi-agent-system",
        "description": "Autonomous multi-agent scientific literature synthesis engine selected for IEEE SPICES (Zenodo DOI: 10.5281/zenodo.22676649). Core architecture: (1) Multi-Source Literature Retrieval querying PubMed, arXiv, Semantic Scholar, and Europe PMC (ingesting 300-800 papers per query); (2) Semantic Embedding Pipeline using Sentence-BERT for abstract encoding; (3) Cosine Similarity Knowledge Graph with similarity threshold pruning and Louvain community clustering; (4) Five Specialized Autonomous Agents for claim extraction with automated Hallucination Guard, evidence mapping, 8-factor study reliability scoring, consensus and contradiction detection, and epistemic uncertainty prioritization; (5) Composite relevance and quality ranking; (6) Fault-Tolerant LLM inference key rotation across Groq LLaMA-3.3-70B; (7) Interactive UI with structured claim explorer and automated reporting.",
        "language": "Python",
        "topics": ["multi-agent-systems", "generative-ai", "scientific-literature-analysis", "graph-clustering", "rag", "ieee-spices", "nlp", "bioinformatics", "python"]
    }
]

CURATED_REPOSITORY_METADATA = {
    "Ultimate-Trader-Dashboard-GitHub-Repository-Structure": {
        "display_name": "Smart Market Watchlist & Real-Time Trading Terminal (Ultimate-Trader-Dashboard)",
        "description": "Stateful market intelligence and real-time trading terminal built with Next.js 15, Express 5, TypeScript, Prisma ORM, PostgreSQL, and Zerodha Kite Connect SDK. Core features: (1) Observation Checkpoints tracking market deltas across user absence intervals (T_checkpoint -> T_now); (2) 4-Factor Attention Scoring Algorithm (0-100 scale synthesizing price swing, volume surge vs 20-day SMA, benchmark alpha divergence vs Nifty 50, and catalyst recency); (3) Tri-State Market Triage Categorization into NEEDS ATTENTION, WORTH A LOOK, and UNCHANGED; (4) SHA-256 Event Continuity Keying preventing duplicate alerts; (5) Zerodha Kite Connect SDK integration with session encryption; (6) Low-latency real-time WebSocket market ticker streams via socket.io; (7) Automated background RSS financial news catalyst worker (scraping Economic Times, LiveMint, Moneycontrol) with multi-LLM sentiment extraction; (8) Paper trading simulation and risk management engine; (9) Docker containerized multi-service deployment.",
        "topics": ["fintech", "nextjs", "typescript", "prisma", "postgresql", "websockets", "zerodha-kite", "trading-terminal", "market-data", "docker"]
    },
    "Ultimate-Trader-Dashboard": {
        "display_name": "Smart Market Watchlist & Real-Time Trading Terminal (Ultimate-Trader-Dashboard)",
        "description": "Stateful market intelligence and real-time trading terminal built with Next.js 15, Express 5, TypeScript, Prisma ORM, PostgreSQL, and Zerodha Kite Connect SDK. Core features: (1) Observation Checkpoints tracking market deltas across user absence intervals (T_checkpoint -> T_now); (2) 4-Factor Attention Scoring Algorithm (0-100 scale synthesizing price swing, volume surge vs 20-day SMA, benchmark alpha divergence vs Nifty 50, and catalyst recency); (3) Tri-State Market Triage Categorization into NEEDS ATTENTION, WORTH A LOOK, and UNCHANGED; (4) SHA-256 Event Continuity Keying preventing duplicate alerts; (5) Zerodha Kite Connect SDK integration with session encryption; (6) Low-latency real-time WebSocket market ticker streams via socket.io; (7) Automated background RSS financial news catalyst worker (scraping Economic Times, LiveMint, Moneycontrol) with multi-LLM sentiment extraction; (8) Paper trading simulation and risk management engine; (9) Docker containerized multi-service deployment.",
        "topics": ["fintech", "nextjs", "typescript", "prisma", "postgresql", "websockets", "zerodha-kite", "trading-terminal", "market-data", "docker"]
    },
    "GenAI-Scientific-Literature-System-multi-agent-system": {
        "display_name": "Multi-Agent Generative AI System for Scientific Literature Analysis (IEEE SPICES / Zenodo DOI: 10.5281/zenodo.22676649)",
        "description": "Autonomous multi-agent biomedical literature synthesis engine published at IEEE SPICES (Zenodo DOI: 10.5281/zenodo.22676649). Core architecture: (1) Multi-Source Literature Retrieval querying PubMed, arXiv, Semantic Scholar, and Europe PMC; (2) Semantic Embedding Pipeline using Sentence-BERT for abstract encoding; (3) Cosine Similarity Knowledge Graph with threshold pruning and Louvain community clustering; (4) Five Specialized Autonomous Agents for claim extraction, evidence mapping to Oxford CEBM levels, 8-factor study reliability evaluation, consensus/contradiction matrix, and epistemic uncertainty prioritization; (5) Relevance-quality composite ranking; (6) Fault-Tolerant LLM key rotation across Groq LLaMA-3.3-70B; (7) Interactive UI with structured claim explorer.",
        "topics": ["multi-agent-systems", "generative-ai", "scientific-literature-analysis", "graph-clustering", "rag", "ieee-spices", "nlp", "bioinformatics", "python"]
    },
    "evidence-grounded-clinical-literature-synthesis": {
        "display_name": "GLAS-Med: Evidence-Grounded Clinical Literature Synthesis (Clinical & Production Enhancement of IEEE SPICES Architecture)",
        "description": "Evidence-grounded clinical literature synthesis pipeline designed as an advanced clinical and production microservice enhancement of the IEEE SPICES literature analysis paper. Core features: (1) Clinical Claim Extraction & PICO Tuple Projection converting unstructured abstracts into Population, Intervention, Comparator, and Outcome claims; (2) 5-Tier Oxford CEBM Hierarchy Classifier stratifying evidence quality from randomized controlled trials to observational studies; (3) Eight-Factor Study Reliability Evaluator assessing sample size, double blinding, randomization, follow-up rates, statistical power, funding bias, trial preregistration, and journal impact; (4) Medical Knowledge Graph Construction with Louvain community detection for clinical topic partitioning; (5) Reliability-Weighted Agreement Metric detecting clinical consensus, resolving controversies, and quarantining low-reliability studies; (6) Epistemic Uncertainty & Research Gap Prioritization highlighting unproven therapies; (7) Microservice Architecture with 9 services including FastAPI, MongoDB document store, Neo4j graph database, FAISS vector search, and Docker Compose deployment.",
        "topics": ["clinical-nlp", "evidence-based-medicine", "knowledge-graphs", "pico-extraction", "oxford-cebm", "multi-agent", "python", "bioinformatics", "fastapi", "docker", "neo4j", "mongodb"]
    },
    "MultiAgent_GenAI_IEEE": {
        "display_name": "Multi-Agent GenAI Scientific Literature Analysis (IEEE Conference Publication Package)",
        "description": "Camera-ready IEEE conference publication package accepted for the IEEE SPICES international conference. Core features: (1) Formatted in standard IEEEtran two-column conference LaTeX class; (2) Standalone Native TikZ & Pgfplots algorithmic architecture diagrams, similarity graph topology visualizations, and agent workflow schematics without external raster assets; (3) Rigorous Mathematical Formalization of the 8-factor reliability formulation (rho), consensus agreement metric (A_k), and epistemic uncertainty priority (U_k); (4) Curated BibTeX Citation Database spanning 50+ peer-reviewed informatics papers; (5) Reproducible Automated PDF Compilation Pipeline achieving zero LaTeX warnings or errors.",
        "topics": ["ieee-spices", "latex", "scientific-writing", "tikz", "pgfplots", "multi-agent-systems", "academic-paper"]
    },
    "neuro_capstone": {
        "display_name": "Multimodal Neuro-Symbolic Platform for Variant Pathogenicity & Biophysical Reasoning",
        "description": "9-layer automated neuro-symbolic platform evaluating missense mutation pathogenicity for late-onset neurodegenerative disorders (Alzheimer's, Parkinson's, ALS, TTR amyloidosis) and Variants of Uncertain Significance (VUS). Core features: (1) Clinical Genetics Consensus Engine aggregating ClinVar, OpenTargets, Ensembl, dbSNP, LOVD, and ClinGen; (2) Automated AlphaFold 3D Protein Structure Indexing and PDB coordinate extraction; (3) Deterministic Structural Biophysics Engine calculating Delta Volume, Kyte-Doolittle Delta Hydrophobicity, Delta Charge, Shrake-Rupley Solvent-Accessible Surface Area (Delta SASA), DSSP secondary structure transitions, steric clashes, and backbone torsion strain; (4) Two-Stage Biophysics-Guided Neural Literature RAG (S-PubMedBERT bi-encoder + TinyBERT cross-encoder reranker); (5) Epistemic Uncertainty Directives (STRUCTURAL_DISCOVERY_VUS) preventing hallucination on unstudied mutations; (6) Calibrated Multi-Model LLM Reasoning Engine with strict server-side PMID validation; (7) Full-Stack Interactive 3D Web Dashboard (FastAPI, React 19, 3Dmol.js mutant visualization, Supabase PostgreSQL).",
        "topics": ["neuro-symbolic", "alphafold", "structural-biology", "bioinformatics", "rag", "fastapi", "react", "3dmoljs", "genomics", "machine-learning"]
    },
    "job-hunter": {
        "display_name": "Autonomous Job Discovery, Career Intelligence & Application Automation Engine",
        "description": "Automated job discovery, semantic candidate matching, and application preparation platform. Core features: (1) Automated Multi-Board Ingestion collecting job postings from LinkedIn, employer portals, and RSS feeds; (2) SQLite Database Persistence with SHA-256 deduplication and lifecycle application tracking (saved, applying, applied, interviewing, rejected); (3) Strict Programmatic Filtering enforcing May 2027 graduation batch gating, Bangalore/remote geo-fencing, and intern/new-grad seniority bounds (zero senior/staff leakage); (4) Semantic Compatibility Scoring (0-100) using Groq LLaMA-3.3-70B; (5) Automated Resume & Cover Letter Tailoring in Markdown and publication-grade PDF via WeasyPrint, dynamically injecting matched codebase accomplishments from candidate GitHub repositories; (6) Full-Stack Web Dashboard & Terminal CLI for real-time portfolio management; (7) Automated Playwright Browser Form Autofill Engine.",
        "topics": ["python", "groq", "llama-3-3-70b", "playwright", "sqlite", "automation", "resume-tailoring", "job-matching", "weasyprint"]
    },
    "oa-arena-windows": {
        "display_name": "OA Arena: Pro Online Assessment Kiosk Simulator & Diagnostic Engine (Windows Edition)",
        "description": "High-fidelity technical hiring kiosk simulator and diagnostic platform replicating corporate online assessments (HackerRank, CodeSignal, CoCubes, Mettl). Core features: (1) Fullscreen Desktop Kiosk Lockdown with strict alwaysOnTop enforcement and frameless window controls via Electron 40; (2) System Shortcut Interception preventing task-switching key combinations (Alt+Tab, Ctrl+Esc, Windows Key, Alt+F4, Ctrl+W, Ctrl+R); (3) Background Distraction App Manager terminating non-whitelisted browser and messaging processes (Discord, Slack, WhatsApp, Chrome) using Windows taskkill; (4) Sandboxed In-Memory Python Code Runner evaluating solutions against public test cases and hidden edge cases; (5) Three-Vector Diagnostic Engine measuring time complexity, space complexity, and edge case resilience; (6) Embedded Monaco Code Editor with custom dark theme, syntax highlighting, and countdown timers; (7) Emergency Unlock Safety Handler (Ctrl+Shift+Alt+Q).",
        "topics": ["electron", "react", "typescript", "monaco-editor", "vite", "tailwind", "express", "kiosk-lockdown", "edtech", "proctoring"]
    },
    "Caregiver-Coordination-Hub": {
        "display_name": "Caregiver Coordination Hub (CS Base Hack4Health 2025)",
        "description": "Collaborative healthcare coordination and caregiving platform for families and healthcare teams (developed for CS Base Hack4Health 2025). Core features: (1) Unified Care Calendar for scheduling medical appointments, family visits, and shared care duties with conflict detection; (2) Medication Adherence Tracker supporting dosage scheduling, administration logging, and overdue medication reminders; (3) Collaborative Shared Care Notes with real-time multi-user syncing for patient status updates; (4) Role-Based Access Control distinguishing primary caregivers, family helpers, and visiting clinicians; (5) Push Notification Alerting Engine for medication alerts and urgent care updates; (6) Fully responsive web client built with React, TypeScript, Material UI (MUI), and Firebase (Authentication, Firestore, Hosting).",
        "topics": ["react", "firebase", "typescript", "mui", "healthcare", "caregiver", "hack4health", "firestore"]
    },
    "CareerTime": {
        "display_name": "CareerTime: LPU-Accelerated AI Career Specialist & Intelligence Advisor",
        "description": "LPU-accelerated AI career advisory and job market intelligence chatbot built with Streamlit, LangChain, Groq LPU inference, and DuckDuckGo Live Web Search. Core features: (1) Ultra-Fast Streaming Inference powered by Groq LPUs with dynamic model switching across llama-3.3-70b-versatile, llama-3.1-8b-instant, and mixtral-8x7b-32768; (2) Live Multi-Query Web Search Intelligence via DuckDuckGo with clickable inline numbered citations [1], [2]; (3) Conversational Intent Classification skipping web search on greetings to deliver sub-second responses; (4) In-Feed Message Editing and question resubmission directly within the chat feed; (5) Persistent Multi-Session History storing conversational trajectories in local JSON storage with click-to-load and deletion; (6) One-Click Trajectory Export in structured JSON format; (7) Modern dark UI (#212121) inspired by ChatGPT with rounded chat bubbles and markdown formatting.",
        "topics": ["streamlit", "langchain", "groq", "lpu", "duckduckgo-search", "career-advisor", "rag", "python", "generative-ai"]
    },
    "Drawing-A-New-Way-To-Search-ML-": {
        "display_name": "Freehand Sketch Recognition & Visual Search Engine (Google QuickDraw)",
        "description": "Multi-model machine learning and deep learning classification system recognizing hand-drawn sketches across 50 object classes from Google's QuickDraw dataset (15+ million drawings). Core features: (1) End-to-End Comparative Benchmark evaluating Logistic Regression baseline (64.64% on 10 classes, 43.89% on 50 classes), multi-kernel SVMs (Linear, RBF, Polynomial deg=5, Sigmoid), custom CNN architectures (v1 through v4 reaching 86.59% accuracy), and Transfer Learning (MobileNet at 75.4%, ResNet50, Inception v3); (2) CNN Architectural Ablation Study systematically testing progressive convolutional layer pruning and pooling alterations; (3) Data Preprocessing & Augmentation Pipeline implementing Cutout spatial square masking and pixel binarization for fast bitmap processing; (4) Interactive HTML5 Canvas Drawing Interface (index.html) enabling live sketch drawing, canvas normalization, and real-time model inference.",
        "topics": ["machine-learning", "deep-learning", "cnn", "svm", "transfer-learning", "quickdraw", "computer-vision", "pytorch", "tensorflow", "python"]
    },
    "Drawing-A-New-Way-To-Search": {
        "display_name": "Freehand Sketch Recognition & Visual Search Engine (Google QuickDraw)",
        "description": "Multi-model machine learning and deep learning classification system recognizing hand-drawn sketches across 50 object classes from Google's QuickDraw dataset (15+ million drawings). Core features: (1) End-to-End Comparative Benchmark evaluating Logistic Regression baseline (64.64% on 10 classes, 43.89% on 50 classes), multi-kernel SVMs (Linear, RBF, Polynomial deg=5, Sigmoid), custom CNN architectures (v1 through v4 reaching 86.59% accuracy), and Transfer Learning (MobileNet at 75.4%, ResNet50, Inception v3); (2) CNN Architectural Ablation Study systematically testing progressive convolutional layer pruning and pooling alterations; (3) Data Preprocessing & Augmentation Pipeline implementing Cutout spatial square masking and pixel binarization for fast bitmap processing; (4) Interactive HTML5 Canvas Drawing Interface (index.html) enabling live sketch drawing, canvas normalization, and real-time model inference.",
        "topics": ["machine-learning", "deep-learning", "cnn", "svm", "transfer-learning", "quickdraw", "computer-vision", "pytorch", "tensorflow", "python"]
    },
    "153_Project3_BD": {
        "display_name": "Distributed High-Throughput Stream & Image Processing Pipeline with Apache Kafka",
        "description": "Fault-tolerant, distributed master-worker stream and image processing architecture built on Apache Kafka, Zookeeper, Docker, Python, OpenCV, and Flask. Core features: (1) Image Partitioning & Task Publishing Engine splitting large images into 512x512 pixel tiles and publishing base64-serialized task payloads to a Kafka tasks topic; (2) Scalable Multi-Worker Consumer Groups pulling tile tasks concurrently to perform parallel compute-intensive transformations (grayscale conversion, edge detection, filtering); (3) Worker Liveness & Heartbeat Telemetry Topic monitoring worker health and re-queuing dropped tasks; (4) Asynchronous Tile Reassembly Engine consuming processed chunks from results topic and stitching tiles back into complete high-resolution output images; (5) Persistent SQLite Job State Store (jobs.db) tracking task progress, dimensions, and execution times; (6) Web Monitoring Dashboard for drag-and-drop image uploads and live rendering.",
        "topics": ["kafka", "apache-kafka", "distributed-systems", "docker", "python", "opencv", "stream-processing", "flask"]
    },
    "AI-Health-Insurance-Verification": {
        "display_name": "AI-Powered Health Insurance Eligibility Verification & Denial Risk Engine",
        "description": "Automated end-to-end health insurance eligibility verification and claim denial risk prediction platform built with FastAPI, Python, SQLAlchemy, Alembic, Docker, and JavaScript. Core features: (1) OCR Document Ingestion Service extracting policy details from scanned medical insurance cards; (2) NLP Information Extraction Pipeline parsing patient demographics, member IDs, group numbers, coverage effective dates, copays, and deductibles; (3) Electronic Data Interchange (EDI) Clearinghouse Integration Service simulating real-time 270 eligibility inquiries and parsing 271 benefit responses; (4) Machine Learning Claim Denial Risk Predictor (denial_risk_model.pkl) estimating claim denial probabilities from coverage discrepancies; (5) Asynchronous Batch Verification Service for high-volume hospital patient rosters; (6) Role-Based Authentication (JWT) and audit logging; (7) Interactive Analytics Dashboard displaying verification throughput, denial trends, and turnaround time.",
        "topics": ["fastapi", "python", "machine-learning", "nlp", "ocr", "healthcare", "insurance-verification", "docker", "sqlalchemy", "alembic"]
    },
    "LoanManagementSystem": {
        "display_name": "Enterprise Loan Management, Delinquency Lifecycle & Restructuring Engine",
        "description": "Enterprise banking and loan management platform built with Java, Spring, and JDBC/MySQL. Core features: (1) Complete Loan Application Lifecycle supporting atomic state transitions (SUBMITTED, VERIFIED, RECOMMENDED, APPROVED, WITHDRAWN) with race condition protection; (2) Document Verification & Rejection-Loop Workflow allowing loan officers to reject illegible documents with specific feedback and enabling customer re-uploads; (3) Active Loan Delinquency & Penalty Engine featuring a 5-day grace period and automated 2% late fee penalty calculation; (4) Scheduled Daily Batch NPA Auto-Flagging Job detecting loans with 3+ consecutive missed EMIs and 90+ days past due, transitioning status to DEFAULTER and notifying recovery teams; (5) Loan Restructuring Service recalculating reduced principal amortization schedules and regenerating remaining EMI terms; (6) Prepayment and Foreclosure Processing; (7) Multi-Role Access Control for Customers, Loan Officers, Underwriters, Recovery Teams, and Branch Managers.",
        "topics": ["java", "spring", "mysql", "jdbc", "fintech", "banking", "loan-management", "amortization", "software-engineering"]
    },
    "Forecasting-Bike-Rental-Demand": {
        "display_name": "Hourly Bike-Sharing Demand Forecasting & Time-Series Regression Pipeline",
        "description": "Machine learning regression system forecasting hourly bicycle rental demand (Capital Bikeshare Washington D.C. dataset) minimizing Root Mean Squared Logarithmic Error (RMSLE). Core features: (1) Data Sanitization & Integrity Validation checking null values, duplicate timestamps, and verifying target consistency (casual + registered == count); (2) Comprehensive Temporal Feature Engineering expanding datetime into hour, month, day of week, and year; (3) Cyclical Trigonometric Encoders (hour_sin, hour_cos) capturing daily continuous periodicity; (4) Peak Rush-Hour Indicator Flags and multicollinearity pruning (removing redundant temperature and holiday flags); (5) Rigorous Model Comparison evaluating 8 regression algorithms (Linear Regression, Support Vector Regressors SVR, Conditional Decision Trees, Random Forest, Gradient Boosting GBM); (6) Leakage-Free 10-Fold Cross-Validation using scikit-learn Pipelines with log-transformed targets (log1p) to directly optimize for RMSLE.",
        "topics": ["machine-learning", "scikit-learn", "time-series", "regression", "feature-engineering", "random-forest", "kaggle", "python", "data-science"]
    },
    "University-DBMS-Management-": {
        "display_name": "University Database Management System & Administrative Web Portal",
        "description": "Full-stack university database management system and administrative portal built with MySQL, Node.js, Express.js, and modern JavaScript GUI. Core features: (1) Normalized Relational Database Schema modeling Students, Faculty, Departments, Courses, Offerings, Enrollments, Grades, Attendance, and Invoices; (2) Advanced SQL Engineering utilizing stored procedures (e.g. course drop procedures), triggers (e.g. enrollment quota validation), and user-defined functions for GPA and fee computation; (3) Materialized Analytical Views for high-enrollment course tracking and grade distribution summaries; (4) ACID Transaction Management guaranteeing data integrity during enrollment and fee payment cycles; (5) Express.js REST API with parameterized queries and input validation; (6) Responsive Web Dashboard supporting student onboarding, faculty course assignments, prerequisite enforcement, attendance tracking, and financial fee invoice generation.",
        "topics": ["mysql", "database-design", "stored-procedures", "sql-triggers", "nodejs", "express", "javascript", "crud", "university-management"]
    },
    "University-Database-Management-System": {
        "display_name": "University Database Management System & Administrative Web Portal",
        "description": "Full-stack university database management system and administrative portal built with MySQL, Node.js, Express.js, and modern JavaScript GUI. Core features: (1) Normalized Relational Database Schema modeling Students, Faculty, Departments, Courses, Offerings, Enrollments, Grades, Attendance, and Invoices; (2) Advanced SQL Engineering utilizing stored procedures (e.g. course drop procedures), triggers (e.g. enrollment quota validation), and user-defined functions for GPA and fee computation; (3) Materialized Analytical Views for high-enrollment course tracking and grade distribution summaries; (4) ACID Transaction Management guaranteeing data integrity during enrollment and fee payment cycles; (5) Express.js REST API with parameterized queries and input validation; (6) Responsive Web Dashboard supporting student onboarding, faculty course assignments, prerequisite enforcement, attendance tracking, and financial fee invoice generation.",
        "topics": ["mysql", "database-design", "stored-procedures", "sql-triggers", "nodejs", "express", "javascript", "crud", "university-management"]
    },
    "PESU_RR_CSE_F_P06_Personal_Wealth_Management_Software_Quadra-Minds": {
        "display_name": "Personal Wealth Management Software (PES University)",
        "description": "Full-stack personal wealth management and financial tracking application built with React 19, Python, Flask, SQLAlchemy, SQLite, and Recharts. Core features: (1) Multi-Class Asset Management tracking physical real estate, gold holdings, stock equity portfolios, and liquid cash accounts; (2) Automated Budget Analysis calculating categorized expenditure, monthly savings ratios, and burn rates; (3) AI-Powered Personalized Financial Recommendations providing tailored savings advice; (4) Secure User Authentication featuring bcrypt password hashing and multi-factor authentication (MFA) support; (5) Interactive Data Visualization with Recharts displaying asset allocation pie charts and net worth growth curves; (6) Automated CI/CD Pipeline via GitHub Actions executing backend pytest and frontend Jest test suites; (7) Responsive UI designed for seamless desktop and mobile tracking.",
        "topics": ["react", "flask", "python", "sqlalchemy", "sqlite", "recharts", "fintech", "wealth-management", "ci-cd", "bcrypt"]
    },
    "PESU_RR_CSE_F_P06_Personal_Wealth_Management_Software": {
        "display_name": "Personal Wealth Management Software (PES University)",
        "description": "Full-stack personal wealth management and financial tracking application built with React 19, Python, Flask, SQLAlchemy, SQLite, and Recharts. Core features: (1) Multi-Class Asset Management tracking physical real estate, gold holdings, stock equity portfolios, and liquid cash accounts; (2) Automated Budget Analysis calculating categorized expenditure, monthly savings ratios, and burn rates; (3) AI-Powered Personalized Financial Recommendations providing tailored savings advice; (4) Secure User Authentication featuring bcrypt password hashing and multi-factor authentication (MFA) support; (5) Interactive Data Visualization with Recharts displaying asset allocation pie charts and net worth growth curves; (6) Automated CI/CD Pipeline via GitHub Actions executing backend pytest and frontend Jest test suites; (7) Responsive UI designed for seamless desktop and mobile tracking.",
        "topics": ["react", "flask", "python", "sqlalchemy", "sqlite", "recharts", "fintech", "wealth-management", "ci-cd", "bcrypt"]
    },
}

IGNORED_DIRS = {
    "node_modules", ".git", ".venv", "dist", "build", ".next",
    "__pycache__", ".pytest_cache", ".DS_Store", ".idea", ".vscode"
}

MANIFEST_FILES = {
    "package.json", "requirements.txt", "pyproject.toml", "Cargo.toml",
    "docker-compose.yml", "docker-compose.yaml", "Dockerfile",
    "schema.prisma", "Makefile", "setup.py"
}


def is_repo_excluded(repo_name: str) -> bool:
    normalized = re.sub(r"[-_]", "", (repo_name or "").lower().strip())
    return any(normalized == re.sub(r"[-_]", "", ex.lower()) for ex in EXCLUDED_REPOSITORIES)


def get_github_username() -> str:
    """Extract GitHub username from environment or parse from resume.md."""
    env_user = os.getenv("GITHUB_USERNAME")
    if env_user:
        return env_user.strip()

    resume_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resume.md")
    if os.path.exists(resume_path):
        try:
            with open(resume_path, "r", encoding="utf-8") as f:
                content = f.read()
                match = re.search(r"github\.com/([a-zA-Z0-9_-]+)", content, re.I)
                if match:
                    return match.group(1).strip()
        except Exception:
            pass

    return "madhavofficial"


def extract_readme_features(readme_text: str) -> list[str]:
    """Extract concrete feature bullet points from README sections."""
    if not readme_text:
        return []

    features = []
    in_features_section = False

    for line in readme_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            header_lower = stripped.lower()
            if any(k in header_lower for k in ["feature", "capabilities", "what it does", "key component", "highlights", "architecture"]):
                in_features_section = True
                continue
            elif in_features_section and any(k in header_lower for k in ["requirement", "setup", "install", "getting started", "prerequisite", "license", "author", "team", "contribut", "disclaimer", "usage", "table of content"]):
                in_features_section = False
                continue

        if in_features_section:
            if stripped.startswith(("-", "*", "•", "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.")):
                clean_bullet = re.sub(r"^[-*•\d\.]+\s*", "", stripped).strip()
                clean_bullet = re.sub(r"^\*\*(.+?)\*\*[:\s-]*", r"\1: ", clean_bullet)
                if clean_bullet and not clean_bullet.startswith("!") and not clean_bullet.startswith("[!["):
                    if len(clean_bullet) > 10 and clean_bullet not in features:
                        features.append(clean_bullet)
                        if len(features) >= 10:
                            break
    return features


def inspect_local_repository(repo_path: str) -> dict:
    """Read full local directory structure, manifests, and architecture files."""
    file_tree = []
    manifests = {}
    readme_text = ""

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
        rel_root = os.path.relpath(root, repo_path)

        for f in files:
            if f.startswith("."):
                continue
            rel_file = os.path.normpath(os.path.join(rel_root, f)) if rel_root != "." else f
            file_tree.append(rel_file)

            if f.lower() == "readme.md" and not readme_text:
                try:
                    with open(os.path.join(root, f), "r", encoding="utf-8", errors="ignore") as fp:
                        readme_text = fp.read()[:10000]
                except Exception:
                    pass

            if f in MANIFEST_FILES or f.endswith(".prisma") or f.endswith(".sql") or f.endswith(".proto"):
                if len(manifests) < 8:  # Cap at 8 key architecture/manifest files
                    try:
                        with open(os.path.join(root, f), "r", encoding="utf-8", errors="ignore") as fp:
                            manifests[rel_file] = fp.read()[:5000]
                    except Exception:
                        pass

    return {
        "file_tree": file_tree[:40],
        "manifests": manifests,
        "readme_text": readme_text,
    }


def inspect_remote_repository(username: str, repo_name: str, headers: dict) -> dict:
    """Fetch remote git tree and manifest files via GitHub CLI or REST API."""
    file_tree = []
    manifests = {}
    readme_text = ""

    # 1. Try authenticated gh CLI first
    try:
        gh_readme = subprocess.run(
            ["gh", "api", f"repos/{username}/{repo_name}/readme"],
            capture_output=True,
            text=True,
            timeout=8
        )
        if gh_readme.returncode == 0:
            res_data = json.loads(gh_readme.stdout)
            raw = res_data.get("content", "")
            if raw:
                readme_text = base64.b64decode(raw).decode("utf-8", errors="ignore")[:10000]

        gh_tree = subprocess.run(
            ["gh", "api", f"repos/{username}/{repo_name}/git/trees/HEAD?recursive=1"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if gh_tree.returncode == 0:
            res_tree = json.loads(gh_tree.stdout)
            tree_data = res_tree.get("tree", []) if isinstance(res_tree, dict) else []
            for item in tree_data:
                path = item.get("path", "")
                if not any(ign in path.split("/") for ign in IGNORED_DIRS):
                    file_tree.append(path)
                    basename = os.path.basename(path)
                    if (basename in MANIFEST_FILES or path.endswith(".prisma") or path.endswith(".sql")) and len(manifests) < 6:
                        f_res = subprocess.run(
                            ["gh", "api", f"repos/{username}/{repo_name}/contents/{path}"],
                            capture_output=True,
                            text=True,
                            timeout=6
                        )
                        if f_res.returncode == 0:
                            f_data = json.loads(f_res.stdout)
                            f_raw = f_data.get("content", "") if isinstance(f_data, dict) else ""
                            if f_raw:
                                manifests[path] = base64.b64decode(f_raw).decode("utf-8", errors="ignore")[:5000]
    except Exception:
        pass

    # 2. Fallback to standard requests if gh failed or returned empty
    if not readme_text or not file_tree:
        try:
            if not readme_text:
                readme_url = f"https://api.github.com/repos/{username}/{repo_name}/readme"
                res = requests.get(readme_url, headers=headers, timeout=6)
                if res.status_code == 200:
                    res_data = res.json()
                    if isinstance(res_data, dict):
                        raw = res_data.get("content", "")
                        if raw:
                            readme_text = base64.b64decode(raw).decode("utf-8", errors="ignore")[:10000]

            if not file_tree:
                tree_url = f"https://api.github.com/repos/{username}/{repo_name}/git/trees/HEAD?recursive=1"
                res = requests.get(tree_url, headers=headers, timeout=8)
                if res.status_code == 200:
                    res_tree = res.json()
                    tree_data = res_tree.get("tree", []) if isinstance(res_tree, dict) else []
                    for item in tree_data:
                        path = item.get("path", "")
                        if not any(ign in path.split("/") for ign in IGNORED_DIRS):
                            file_tree.append(path)
                            basename = os.path.basename(path)
                            if (basename in MANIFEST_FILES or path.endswith(".prisma") or path.endswith(".sql")) and len(manifests) < 6:
                                f_url = f"https://api.github.com/repos/{username}/{repo_name}/contents/{path}"
                                f_res = requests.get(f_url, headers=headers, timeout=6)
                                if f_res.status_code == 200:
                                    f_data = f_res.json()
                                    if isinstance(f_data, dict):
                                        f_raw = f_data.get("content", "")
                                        if f_raw:
                                            manifests[path] = base64.b64decode(f_raw).decode("utf-8", errors="ignore")[:5000]
        except Exception as e:
            print(f"Warning: Failed remote inspection for '{repo_name}': {e}", file=sys.stderr)

    return {
        "file_tree": file_tree[:40],
        "manifests": manifests,
        "readme_text": readme_text,
    }


def fetch_github_portfolio(username: str = None, force_refresh: bool = False) -> list[dict]:
    """Fetch all repositories with deep codebase inspection (local first, then remote)."""
    username = username or get_github_username()

    if not force_refresh and os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
                cached_time = cached_data.get("timestamp", 0)
                if time.time() - cached_time < CACHE_TTL_SECONDS and cached_data.get("username") == username:
                    repos = cached_data.get("repositories", [])
                    return [r for r in repos if not is_repo_excluded(r.get("name", ""))]
        except Exception as e:
            print(f"Warning: Failed to read GitHub cache: {e}", file=sys.stderr)

    headers = {
        "User-Agent": "JobHunter-Codebase-Inspector/2.0",
        "Accept": "application/vnd.github.v3+json",
    }
    github_token = os.getenv("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    # 1. Try gh CLI first for full collaborator & org repo access
    repos = []
    try:
        gh_res = subprocess.run(
            ["gh", "api", "user/repos?affiliation=owner,collaborator,organization_member", "--paginate"],
            capture_output=True,
            text=True,
            timeout=12
        )
        if gh_res.returncode == 0:
            repos = json.loads(gh_res.stdout)
    except Exception:
        pass

    # 2. Fallback to standard GitHub REST API
    if not repos:
        try:
            url = f"https://api.github.com/users/{username}/repos?per_page=100&sort=updated"
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                repos = res.json()
        except Exception as e:
            print(f"Warning: GitHub API error: {e}", file=sys.stderr)

    # 3. Always ensure featured research & organization repositories are included
    for feat in FEATURED_EXTERNAL_REPOSITORIES:
        if not any(r.get("name") == feat["name"] for r in repos):
            repos.append({
                "name": feat["name"],
                "full_name": feat["full_name"],
                "owner": {"login": feat["owner"]},
                "html_url": feat["url"],
                "description": feat["description"],
                "language": feat["language"],
                "topics": feat["topics"],
                "fork": False
            })

    portfolio = []
    seen_names = set()

    for r in repos:
        if r.get("fork", False):
            continue
        name = r.get("name", "")
        full_name = r.get("full_name", f"{username}/{name}")
        owner_login = r.get("owner", {}).get("login", username)
        
        if is_repo_excluded(name) or name in seen_names:
            continue
        seen_names.add(name)

        curated = CURATED_REPOSITORY_METADATA.get(name, {})
        description = curated.get("description") or r.get("description") or ""
        topics = curated.get("topics") or r.get("topics") or []
        display_name = curated.get("display_name") or name
        language = r.get("language") or ""
        html_url = r.get("html_url") or f"https://github.com/{full_name}"

        # Resolve repository locally across common workspace paths
        candidate_paths = [
            os.path.join(USER_HOME, name),
            os.path.join(USER_HOME, "Documents", "GitHub", name),
            os.path.join(USER_HOME, "Documents", name),
        ]
        alt_name = name.replace("_", "-") if "_" in name else name.replace("-", "_")
        candidate_paths.extend([
            os.path.join(USER_HOME, alt_name),
            os.path.join(USER_HOME, "Documents", "GitHub", alt_name),
            os.path.join(USER_HOME, "Documents", alt_name),
        ])

        local_path = next((p for p in candidate_paths if os.path.isdir(p)), None)
        if local_path:
            inspection = inspect_local_repository(local_path)
            source_type = "local_filesystem"
        else:
            inspection = inspect_remote_repository(owner_login, name, headers)
            source_type = "remote_github"

        # Fallback to manifest description if still empty
        if not description:
            for m_path, m_content in inspection.get("manifests", {}).items():
                if "package.json" in m_path:
                    try:
                        pkg_data = json.loads(m_content)
                        if pkg_data.get("description"):
                            description = pkg_data.get("description")
                            break
                    except Exception:
                        pass

        # If description doesn't yet contain detailed features, extract them from README
        extracted_features = extract_readme_features(inspection.get("readme_text", ""))
        if extracted_features and "Core features" not in description and "Features:" not in description:
            feat_str = "; ".join(f"({i+1}) {f}" for i, f in enumerate(extracted_features[:8]))
            if description:
                description = f"{description.rstrip('. ')}. Core features: {feat_str}."
            else:
                description = f"Core features: {feat_str}."

        project_item = {
            "name": name,
            "display_name": display_name,
            "full_name": full_name,
            "owner": owner_login,
            "url": html_url,
            "language": language,
            "description": description,
            "topics": topics,
            "source_type": source_type,
            "file_tree": inspection.get("file_tree", []),
            "manifests": inspection.get("manifests", {}),
            "readme_content": inspection.get("readme_text", ""),
        }
        portfolio.append(project_item)

    # Save to cache
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "username": username,
                "timestamp": time.time(),
                "repositories": portfolio
            }, f, indent=2)
    except Exception as e:
        print(f"Warning: Failed to save GitHub portfolio cache: {e}", file=sys.stderr)

    return portfolio


def format_github_portfolio_for_prompt(portfolio: list[dict]) -> str:
    """Format deep codebase inspection data into a compact, high-density context for LLM project selection and bullet generation."""
    if not portfolio:
        return "No external GitHub repositories found."

    sections = []
    for p in portfolio:
        p_name = p.get("display_name") or p.get("name", "")
        p_url = p.get("url", "")
        p_desc = p.get("description", "")
        lang = p.get("language") or "N/A"
        file_tree = p.get("file_tree") or []
        manifests = p.get("manifests") or {}
        readme = p.get("readme_content") or ""

        deps = []
        low_signal_deps = {"uuid", "dotenv", "cookie-parser", "cors", "react-dom", "nodemon", "ts-node", "ts-node-dev"}
        for m_path, m_content in manifests.items():
            if "package.json" in m_path:
                try:
                    data = json.loads(m_content)
                    for k in list(data.get("dependencies", {}).keys()):
                        if not k.startswith("@types/") and k.lower() not in low_signal_deps and k not in deps:
                            deps.append(k)
                except Exception:
                    pass
            elif "requirements.txt" in m_path:
                for line in m_content.splitlines():
                    cleaned = line.split("==")[0].split(">=")[0].strip()
                    if cleaned and not cleaned.startswith("#") and cleaned.lower() not in low_signal_deps and cleaned not in deps:
                        deps.append(cleaned)

        block = f"### Project: {p_name}\n"
        block += f"- **Repository**: {p_url}\n"
        block += f"- **Primary Language**: {lang}"
        if deps:
            block += f" | Key Dependencies: {', '.join(deps[:10])}"
        block += "\n"
        if p_desc:
            block += f"- **Overview & Core Features**: {p_desc}\n"

        sections.append(block)

    return "\n".join(sections)
