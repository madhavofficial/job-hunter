"""Deterministic safeguards shared by matching and dashboard generation."""

import re

KNOWN_ENTERPRISES = {
    # Global IT Services & Consultancies
    "infosys", "tcs", "tata consultancy services", "wipro", "cognizant",
    "capgemini", "accenture", "ibm", "hcl", "tech mahindra", "ltimindtree",
    "genpact", "ust", "indium", "hexaware", "mphasis", "birlasoft", "coforge",
    "zensar", "cyient", "virtusa", "persistent systems",
    # Global Tech, Hardware & Telecom
    "google", "microsoft", "amazon", "apple", "meta", "nvidia", "intel", "amd",
    "qualcomm", "broadcom", "cisco", "oracle", "sap", "salesforce", "adobe",
    "dell", "hp", "hpe", "hewlett packard enterprise", "hewlett packard",
    "teradata", "ptc", "eaton", "siemens", "bosch", "philips", "honeywell",
    "general electric", "ge", "hitachi", "hitachi energy", "micron technology",
    "samsung", "sony", "bt group", "comcast",
    # Global Finance & Banking
    "jpmorgan", "jpmorganchase", "goldman sachs", "morgan stanley", "citi",
    "citigroup", "barclays", "wells fargo", "hsbc", "standard chartered",
    "deutsche bank", "bnp paribas", "ubs", "blackrock", "fidelity", "mastercard",
    "visa", "american express", "paypal", "nuvama", "idfc", "morningstar",
    "munich re", "metlife", "natwest", "natwest group", "lpl financial",
    # Global Healthcare / Pharma / Life Sciences
    "novartis", "amgen", "solventum", "edwards lifesciences", "pfizer",
    "johnson & johnson", "astrazeneca", "electronic arts", "ea",
    "scientific games", "nielsen", "nielsen iq", "dhl", "fedex", "walmart",
    "target", "pearson", "celonis", "anaplan", "servicenow", "workday",
    "snowflake", "databricks", "splunk", "vmware", "atlassian", "intuit",
    "autodesk", "atkinsréalis", "wsp", "ixigo", "stripe",
}

KNOWN_PRODUCT_COMPANIES = {
    "openai", "anthropic", "google", "microsoft", "stripe", "swiggy", "zerodha",
    "postman", "razorpay", "gitlab", "carousell", "freight tiger", "coram ai",
    "weekday ai", "everseen", "revolte ai", "peryx ai", "startx med",
    "coderound ai", "juicelabs ai", "wisdomai", "whatfix", "spearmint technologies",
    "zenup health", "hasamex", "engradar", "deskbuddy", "newspace research",
    "42 learn", "blackhawk network", "nxtpe",
}

AGENCY_MARKERS = (
    "zepcruit", "hiringhood", "principle pride", "top gen ai jobs", "minute sourcing",
    "codepillars", "rediente", "staffing", "workforce", "recruit", "rytloop",
    "genesect", "rythiring", "absolutehub", "tasks expert", "zenithbyte", "nexal iit",
    "sparks to ideas", "sourcing", "uplers", "dasp digital", "zerotwo", "jansoft",
    "recruitment", "headhunter", "manpower", "talent acquisition", "consulting",
)

ENTERPRISE_PATTERNS = tuple(re.compile(rf"\b{re.escape(name)}\b", re.I) for name in sorted(KNOWN_ENTERPRISES, key=len, reverse=True))


import sqlite3
from typing import Optional
import company_classifier


def classify_company_tier(company: str, conn: Optional[sqlite3.Connection] = None) -> str:
    category = company_classifier.get_company_category(company, conn=conn, allow_network=False)
    tier_map = {
        "Big Tech & Global MNC": "Tier 1: Big Tech & Global MNC",
        "Unicorn / Tech Giant": "Tier 1: Unicorn / Tech Giant",
        "AI & Tech Startup": "Tier 1: AI & Tech Startup",
        "IT Services & Consultancies": "Tier 2: IT Services & Consultancies",
        "Staffing Agency / Unverified": "Tier 3: Staffing Agency / Unverified",
    }
    return tier_map.get(category, "Tier 3: Staffing Agency / Unverified")


def is_explicitly_unverified_company(company: str) -> bool:
    """Check whether employer has explicit agency/consultancy markers or placeholder names.
    
    Preserves the hard-filter contract: ordinary unknown employers pass into discovery
    where quality scoring rates them lower, but explicit agencies/placeholders are rejected.
    """
    norm = company_classifier.normalize_company_key(company)
    if not norm or norm in company_classifier.PLACEHOLDER_NAMES:
        return True
    if any(marker in norm for marker in company_classifier.AGENCY_MARKERS):
        return True
    return False


def deterministic_hard_filter(job: dict) -> tuple[bool, str | None]:
    """Reject obvious false positives before spending an LLM request."""
    title = str(job.get("title") or "")
    company = str(job.get("company") or "")
    location = str(job.get("location") or "")
    description = str(job.get("description") or "")
    experience = str(job.get("experience_range") or "")
    searchable = f"{title}\n{description}\n{experience}".lower()

    # Preserve the deterministic hard-filter contract for ordinary unknown
    # employers; the stricter quality gate rejects them before recommendation.
    if is_explicitly_unverified_company(company):
        return False, "Company appears to be a staffing agency, consultancy, or unverified aggregator."
    if re.search(r"\b(?:senior|sr\.?|lead|principal|staff|manager|director|head)\b", title, re.I):
        return False, "Role title indicates senior/leadership experience beyond the candidate's internship level."
    if re.search(r"\b(?:ph\.?d\.?|doctoral|doctorate|postdoc|postdoctoral)\b", title, re.I):
        return False, "Role targets PhD/Doctoral candidates; candidate is an undergraduate B.Tech student."
    if re.search(r"\b(?:enrolled in a ph\.?d|pursuing a ph\.?d|ph\.?d (?:candidate|student|degree) required|must be enrolled in a (?:ph\.?d|doctoral))\b", searchable, re.I):
        return False, "Job explicitly requires enrollment in or completion of a PhD/Doctoral program."
    if re.search(r"\b(?:mba|master of business administration)\b", title, re.I):
        return False, "Role targets MBA candidates; candidate is a B.Tech CSE student."
    if re.search(r"\b(?:enrolled in an? mba|pursuing an? mba|must be enrolled in an? mba|mba (?:candidate|student|intern|internship)|(?:mba|master of business administration)\s*(?:students?|interns?|candidates?|graduates?|required|only))\b", searchable, re.I):
        return False, "Job explicitly requires enrollment in or completion of an MBA program."
    if re.search(r"\b(?:[3-9]|[1-9][0-9])\s*\+?\s*(?:years?|yrs?)\b", searchable, re.I):
        return False, "Job explicitly requires at least three years of professional experience."
    if re.search(r"(?:2025|2026)\s*(?:batch|graduates?|pass[- ]?out)|(?:batch|graduates?|pass[- ]?out)\s*(?:of\s*)?(?:2025|2026)", searchable, re.I):
        return False, "Job explicitly targets 2025/2026 graduates rather than the candidate's 2027 batch."

    outside_india = r"\b(?:united states|u\.s\.a?\.?|canada|united kingdom|u\.k\.?|australia|germany|france|singapore|dubai|uae)\b"
    if re.search(outside_india, location, re.I) and not re.search(r"\bindia\b|\bremote\b", location, re.I):
        return False, "Location is outside India and is not remote."
    return True, None


def is_job_truly_remote(job: dict) -> bool:
    """Strictly validates whether a job is verified Remote / Work-From-Home.
    
    Rejects on-site and hybrid roles located in physical cities/offices even if
    an aggregator marked them with a remote flag.
    """
    loc = str(job.get("location") or "").lower().strip()
    title = str(job.get("title") or "").lower().strip()
    desc = str(job.get("description") or "").lower()

    # 1. Negative Disqualifiers: Explicit On-Site or Hybrid terms
    if any(term in loc for term in ("on-site", "onsite", "in-office", "hybrid", "office only")):
        return False
    if any(term in title for term in ("on-site", "onsite", "in-office", "hybrid")):
        return False

    # 2. Strict Positive Confirmation in Location or Title
    remote_markers = ("remote", "work from home", "wfh", "anywhere", "telecommute")
    if any(m in loc for m in remote_markers) or any(m in title for m in remote_markers):
        return True

    # 3. Disqualify physical city/state locations (e.g. 'KA, IN', 'MH, IN', 'Bengaluru', 'Navi Mumbai', 'Mohali')
    physical_indicators = (
        ", in", "karnataka", "bangalore", "bengaluru", "mumbai", "pune", "delhi", "hyderabad",
        "chennai", "noida", "gurgaon", "gurugram", "ahmedabad", "kolkata", "kochi", "kerala",
        "tamil nadu", "maharashtra", "telangana", "andhra", "punjab", "haryana", "uttar pradesh",
        "gujarat", "west bengal", "district"
    )
    if any(p in loc for p in physical_indicators):
        if "100% remote" in desc or "fully remote" in desc or "work from anywhere" in desc:
            return True
        return False

    if "100% remote" in desc or "fully remote" in desc or "work from anywhere" in desc:
        return True

    return False
