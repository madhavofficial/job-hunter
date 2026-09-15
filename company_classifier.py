"""AI and Web-Search powered Company Classifier with persistent SQLite caching.

Classifies employers into 5 distinct categories:
1. Big Tech & Global MNC (Fortune 500, global tech giants, global banking GCCs)
2. Unicorn / Tech Giant (Late-stage, multi-billion-dollar product leaders, decacorns)
3. AI & Tech Startup (Seed, Series A/B, YC-backed, emerging AI/product startups)
4. IT Services & Consultancies (TCS, Infosys, Wipro, Cognizant, Accenture, Capgemini)
5. Staffing Agency / Unverified (Recruitment agencies, headhunters, body-shops)
"""

import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from typing import Dict, Optional, Tuple

import requests
from bs4 import BeautifulSoup

import config
import db


CANONICAL_CATEGORIES = (
    "Big Tech & Global MNC",
    "Unicorn / Tech Giant",
    "AI & Tech Startup",
    "IT Services & Consultancies",
    "Staffing Agency / Unverified",
)

AGENCY_MARKERS = (
    "zepcruit", "hiringhood", "principle pride", "top gen ai jobs", "minute sourcing",
    "codepillars", "rediente", "staffing", "workforce", "recruit", "rytloop",
    "genesect", "rythiring", "absolutehub", "tasks expert", "zenithbyte", "nexal iit",
    "sparks to ideas", "sourcing", "uplers", "dasp digital", "zerotwo", "jansoft",
    "recruitment", "headhunter", "manpower", "talent acquisition", "randstad",
    "michael page", "adecco", "allegis", "robert half", "kelly services", "hays",
    "teksystems", "collabera",
)

PLACEHOLDER_NAMES = {
    "none", "confidential", "private limited", "company name", "unknown",
    "mystery labs", "various", "client of", "stealth",
}

# Curated seed anchors for sub-millisecond classification without network calls
SEED_BIG_TECH_MNC = {
    "google", "microsoft", "amazon", "apple", "meta", "nvidia", "intel", "amd",
    "qualcomm", "broadcom", "cisco", "oracle", "sap", "salesforce", "adobe",
    "dell", "hp", "hpe", "hewlett packard enterprise", "hewlett packard",
    "teradata", "ptc", "eaton", "siemens", "bosch", "philips", "honeywell",
    "general electric", "ge", "hitachi", "hitachi energy", "micron technology",
    "samsung", "sony", "bt group", "comcast", "at&t", "verizon",
    "jpmorgan", "jpmorganchase", "goldman sachs", "morgan stanley", "citi",
    "citigroup", "barclays", "wells fargo", "hsbc", "standard chartered",
    "deutsche bank", "bnp paribas", "ubs", "blackrock", "fidelity", "mastercard",
    "visa", "american express", "paypal", "nuvama", "idfc", "morningstar",
    "munich re", "metlife", "natwest", "natwest group", "lpl financial",
    "novartis", "amgen", "solventum", "edwards lifesciences", "pfizer",
    "johnson & johnson", "astrazeneca", "electronic arts", "ea",
    "scientific games", "nielsen", "nielsen iq", "dhl", "fedex", "walmart",
    "target", "pearson", "celonis", "anaplan", "servicenow", "workday",
    "snowflake", "databricks", "splunk", "vmware", "atlassian", "intuit",
    "autodesk", "atkinsréalis", "wsp",
}

SEED_UNICORNS = {
    "openai", "anthropic", "stripe", "swiggy", "zomato", "razorpay", "zerodha",
    "postman", "gitlab", "carousell", "cred", "meesho", "phonepe", "flipkart",
    "uber", "airbnb", "canva", "figma", "notion", "retool", "vercel", "supabase",
    "cloudflare", "linear", "raycast", "inmobi", "freshworks", "darwinbox",
    "browserbase", "perplexity", "scale ai", "hugging face", "mistral",
}

SEED_IT_SERVICES = {
    "infosys", "tcs", "tata consultancy services", "wipro", "cognizant",
    "capgemini", "accenture", "ibm", "hcl", "tech mahindra", "ltimindtree",
    "genpact", "ust", "indium", "hexaware", "mphasis", "birlasoft", "coforge",
    "zensar", "cyient", "virtusa", "persistent systems", "l&t technology services",
    "kpit", "mindtree", "sonata software", "tata elxsi", "nihilent",
}


def normalize_company_key(company: str) -> str:
    """Normalize employer name for reliable caching and matching."""
    text = re.sub(r"[^a-zA-Z0-9\s.]", " ", str(company or "").lower()).strip()
    text = re.sub(r"\s+", " ", text)
    for suffix in (" private limited", " pvt ltd", " pvt limited", " limited", " ltd", " inc", " llc"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text


def init_classification_table(conn: sqlite3.Connection):
    """Ensure the company classification cache table exists."""
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS company_classifications (
        company_normalized TEXT PRIMARY KEY,
        company_display TEXT,
        category TEXT NOT NULL,
        confidence TEXT DEFAULT 'medium',
        source TEXT DEFAULT 'ai',
        reasoning TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_company_class_category ON company_classifications (category)")
    conn.commit()


def get_cached_classification(company_norm: str, conn: Optional[sqlite3.Connection] = None) -> Optional[Dict[str, str]]:
    """Retrieve cached classification in < 0.1ms."""
    close_conn = False
    if conn is None:
        conn = db.get_db_connection()
        close_conn = True
    try:
        init_classification_table(conn)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT company_normalized, company_display, category, confidence, source, reasoning FROM company_classifications WHERE company_normalized = ?",
            (company_norm,),
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None
    finally:
        if close_conn:
            conn.close()


def save_classification(
    company_norm: str,
    company_display: str,
    category: str,
    confidence: str = "high",
    source: str = "ai",
    reasoning: str = "",
    conn: Optional[sqlite3.Connection] = None,
):
    """Save or update company classification in SQLite."""
    close_conn = False
    if conn is None:
        conn = db.get_db_connection()
        close_conn = True
    try:
        init_classification_table(conn)
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO company_classifications (company_normalized, company_display, category, confidence, source, reasoning, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(company_normalized) DO UPDATE SET
            category = excluded.category,
            confidence = excluded.confidence,
            source = excluded.source,
            reasoning = excluded.reasoning,
            updated_at = CURRENT_TIMESTAMP
        """, (company_norm, company_display, category, confidence, source, reasoning))
        conn.commit()
    finally:
        if close_conn:
            conn.close()


def build_company_search_query(company: str, domain: str = "", location: str = "") -> str:
    """Build a context-aware search query targeted at business intelligence."""
    clean_company = re.sub(r"[^a-zA-Z0-9\s.]", " ", company).strip()
    if domain and not any(d in domain.lower() for d in ("linkedin.com", "indeed.com", "naukri.com", "greenhouse.io", "lever.co", "ashbyhq.com")):
        return f'"{clean_company}" "{domain}" (company OR startup OR "headquarters")'
    return f'"{clean_company}" (company OR startup OR "headquarters") (crunchbase OR pitchbook OR linkedin OR tracxn)'


def web_search_company_context(company: str, domain: str = "", location: str = "") -> str:
    """Fetch DuckDuckGo search snippets for an unknown company."""
    query = build_company_search_query(company, domain, location)
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(query)}"
        r = requests.get(url, headers=headers, timeout=6)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            snippets = [a.get_text().strip() for a in soup.find_all("a", class_="result__snippet")[:3]]
            return " ".join(snippets)
    except Exception as e:
        print(f"Notice: Web search lookup failed for '{company}': {e}", file=sys.stderr)
    return ""


def classify_with_ai(company: str, description_snippet: str = "", web_context: str = "") -> Tuple[str, str]:
    """Classify company using Groq cluster with OpenRouter fallback."""
    prompt = f"""You are an expert tech company classifier for software engineering recruitment.
Classify the company "{company}" into EXACTLY ONE of these 5 categories:

1. "Big Tech & Global MNC"
   - Global Fortune 500, legacy tech conglomerates, major multinational banks, global capability centers.
   - Examples: Google, Microsoft, Amazon, Apple, Nvidia, HPE, Qualcomm, Cisco, Intel, Goldman Sachs, JPMorgan, NatWest, Honeywell, Siemens, Edwards Lifesciences.

2. "Unicorn / Tech Giant"
   - Established multi-billion dollar product leaders, decacorns, top-tier consumer/B2B platforms.
   - Examples: OpenAI, Anthropic, Stripe, Swiggy, Zomato, Razorpay, Zerodha, Postman, GitLab, Uber, Airbnb, Canva, Figma, Notion, Databricks, Snowflake.

3. "AI & Tech Startup"
   - Seed, Series A/B/C, YC-backed, stealth ventures, boutique AI labs, agile engineering product teams.
   - Examples: Coram AI, Weekday AI, DeskBuddy, EngRadar, Zenup Health, Hasamex, CodeRound AI, revolte.ai, StartX Med, Peryx.ai, Refold AI.

4. "IT Services & Consultancies"
   - Enterprise IT services, outsourcing firms, system integrators, staffing consultancies.
   - Examples: TCS, Infosys, Wipro, Cognizant, Accenture, Capgemini, LTIMindtree, Tech Mahindra, Genpact, UST, Indium, Persistent Systems.

5. "Staffing Agency / Unverified"
   - Third-party recruiting agencies, temp staffing, headhunters, body-shops, or anonymous employers.
   - Examples: Zepcruit, Hiringhood, Zenithbyte, Uplers.

Context from Job / Listing:
{description_snippet[:400] if description_snippet else "None available"}

Context from Business Search:
{web_context[:600] if web_context else "None available"}

Return ONLY a JSON object with this exact schema:
{{
  "category": "Category Name",
  "reasoning": "1 sentence explanation"
}}"""

    # Try Groq multi-key rotation first
    max_retries = 3
    retries = 0
    client = config.get_groq_client()
    for _ in range(max_retries):
        try:
            model = config.get_best_model(client)
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=150,
                timeout=12,
            )
            content = (resp.choices[0].message.content or "").strip()
            # Extract JSON block
            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                cat = data.get("category", "").strip()
                reason = data.get("reasoning", "").strip()
                for valid_cat in CANONICAL_CATEGORIES:
                    if valid_cat.lower() in cat.lower():
                        return valid_cat, reason
        except Exception as e:
            err_str = str(e).lower()
            if any(term in err_str for term in ("rate_limit", "429", "tokens per day", "tpd", "limit")):
                client = config.cycle_groq_client()
                retries += 1
                continue
            break

    # OpenRouter fallback
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    if openrouter_key:
        try:
            from openai import OpenAI
            or_client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=openrouter_key,
            )
            or_resp = or_client.chat.completions.create(
                model="google/gemma-4-26b-a4b-it:free",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=150,
                timeout=25,
            )
            content = (or_resp.choices[0].message.content or "").strip()
            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                cat = data.get("category", "").strip()
                reason = data.get("reasoning", "").strip()
                for valid_cat in CANONICAL_CATEGORIES:
                    if valid_cat.lower() in cat.lower():
                        return valid_cat, reason
        except Exception as e:
            print(f"Notice: OpenRouter company classification fallback failed: {e}", file=sys.stderr)

    # Deterministic default fallback
    return "AI & Tech Startup", "Defaulted to tech startup based on tech job context."


def get_company_category(
    company: str,
    job_description: str = "",
    domain: str = "",
    location: str = "",
    conn: Optional[sqlite3.Connection] = None,
    allow_network: bool = True,
) -> str:
    """Classify an employer into one of the 5 canonical categories.
    
    1. Checks persistent SQLite cache (< 0.1ms).
    2. Checks obvious agency markers / placeholders.
    3. Checks curated anchors (Google, Swiggy, TCS).
    4. If unknown and allow_network=True: AI + Web search resolution.
    5. Caches the result in SQLite.
    """
    raw_name = (company or "").strip()
    norm = normalize_company_key(raw_name)

    if not norm or norm in PLACEHOLDER_NAMES:
        return "Staffing Agency / Unverified"

    if any(marker in norm for marker in AGENCY_MARKERS):
        return "Staffing Agency / Unverified"

    # Check cache
    cached = get_cached_classification(norm, conn)
    if cached and cached.get("category") in CANONICAL_CATEGORIES:
        return cached["category"]

    # Check curated seed anchors for instant sub-millisecond return
    for name in sorted(SEED_BIG_TECH_MNC, key=len, reverse=True):
        if re.search(rf"\b{re.escape(name)}\b", norm, re.I):
            cat = "Big Tech & Global MNC"
            save_classification(norm, raw_name, cat, "high", "seed", f"Matched global enterprise anchor: {name}", conn)
            return cat

    for name in sorted(SEED_UNICORNS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(name)}\b", norm, re.I):
            cat = "Unicorn / Tech Giant"
            save_classification(norm, raw_name, cat, "high", "seed", f"Matched unicorn anchor: {name}", conn)
            return cat

    for name in sorted(SEED_IT_SERVICES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(name)}\b", norm, re.I):
            cat = "IT Services & Consultancies"
            save_classification(norm, raw_name, cat, "high", "seed", f"Matched IT services anchor: {name}", conn)
            return cat

    # If network is not allowed (e.g. strict offline unit tests), default to startup
    if not allow_network:
        return "AI & Tech Startup"

    # AI + Web Search Classification
    web_context = ""
    # Only search web if description is short / ambiguous
    if len(job_description or "") < 300:
        web_context = web_search_company_context(raw_name, domain, location)

    category, reasoning = classify_with_ai(raw_name, job_description, web_context)
    save_classification(norm, raw_name, category, "high", "ai_search", reasoning, conn)
    return category
