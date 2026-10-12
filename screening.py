"""Deterministic safeguards shared by matching and dashboard generation."""

import re

AGENCY_MARKERS = (
    "staffing", "workforce", "recruit", "sourcing", "uplers", "headhunter", "manpower",
    "talent acquisition", "consulting", "body shop", "placement consultancy",
)


import sqlite3
from typing import Optional
import company_classifier


_INDIA_TEXT = re.compile(
    r"\b(?:india|indian|bharat|bengaluru|bangalore|hyderabad|pune|mumbai|delhi|new delhi|"
    r"noida|gurugram|gurgaon|chennai|kolkata|ahmedabad|kochi|kerala|karnataka|tamil nadu|"
    r"maharashtra|telangana|gujarat|chandigarh|jaipur|indore|bhopal|coimbatore|"
    r"trivandrum|thiruvananthapuram|ncr)\b",
    re.I,
)
_INDIA_CODES = {"in", "ind"}
_GLOBAL_TEXT = re.compile(r"\b(?:global|worldwide|anywhere)\b", re.I)
_NON_INDIA_TEXT = re.compile(
    r"\b(?:united states|u\.s\.a?\.?|usa|\bus\b|\bgb\b|san francisco|new york|nyc|seattle|austin|"
    r"california|los angeles|chicago|boston|london|berlin|paris|tokyo|toronto|canada|\buk\b|"
    r"united kingdom|australia|sydney|singapore|germany|france|amer|emea|latam|apac|"
    r"belgrade|dubai|abu dhabi|\buae\b|vietnam|malaysia|hong kong|ireland|dublin|"
    r"netherlands|amsterdam|poland|sweden|brazil|mexico|israel|taiwan|korea|japan|"
    r"philippines|indonesia|thailand|spain|italy|portugal|romania|europe|"
    r"north america|south america|united arab|indiana|indianapolis)\b",
    re.I,
)


def is_open_application_title(title: str) -> bool:
    """True for talent-pool forms that are not a specific role."""
    text = str(title or "").lower()
    return "general application" in text or "don't see a fit" in text or "do not see a fit" in text


def is_india_or_worldwide(location: str, is_remote: bool = False) -> bool:
    """Keep India roles and explicitly worldwide roles.

    Bare "Remote", "Remote US", and "Remote - International" are rejected.
    The Lever country code is the standalone segment "; IN". The US state
    abbreviation ", IN" (Indiana) does not count. A remote flag does not
    override a missing India or worldwide location.
    """
    del is_remote
    loc = (location or "").strip().lower()
    if not loc:
        return False
    if _INDIA_TEXT.search(loc):
        return True
    # Check outside-India text before the country code so "Brownsburg, IN; US"
    # cannot pass on the letters IN.
    if _NON_INDIA_TEXT.search(loc):
        return False
    segments = [part.strip() for part in loc.split(";") if part.strip()]
    if any(part in _INDIA_CODES for part in segments):
        return True
    if _GLOBAL_TEXT.search(loc):
        return True
    return False


def is_dashboard_listing(job: dict) -> bool:
    """Shortlist rows are direct employer postings in India or an explicit worldwide role."""
    from quality import INTENTIONAL_SITES, has_direct_employer_signal

    if is_open_application_title(job.get("title")):
        return False
    if not has_direct_employer_signal(job):
        return False
    site = str(job.get("site") or "").lower()
    if site in INTENTIONAL_SITES:
        return True
    return is_india_or_worldwide(str(job.get("location") or ""), bool(job.get("is_remote")))


def classify_company_tier(
    company: str,
    conn: Optional[sqlite3.Connection] = None,
    allow_network: bool = False,
    job_description: str = "",
) -> str:
    category = company_classifier.get_company_category(
        company, job_description=job_description, conn=conn, allow_network=allow_network,
    )
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

    NON_CSE_TITLE_MARKERS = (
        "video editor", "graphic designer", "content writer", "content creator", "telecaller",
        "tele caller", "receptionist", "legal counsel", "corporate counsel", "counsel",
        "financial analyst", "operations associate", "operations specialist", "contracting operations",
        "voice support", "customer support", "customer success", "sales", "marketing", "account executive",
        "business development", "recruiter", "recruitment", "human resources", "talent acquisition",
        "hr associate", "hr partner", "manufacturing design", "civil", "structural", "chemical",
        "copywriter", "social media", "event manager", "store manager", "office administrator",
        "executive assistant", "delivery executive", "delivery boy", "delivery girl", "delivery partner",
        "loading and unloading", "relationship executive", "relationship manager", "field officer",
        "driver", "security guard", "housekeeping", "warehouse associate", "branch manager",
    )
    title_lower = title.lower()
    if any(marker in title_lower for marker in NON_CSE_TITLE_MARKERS):
        return False, "Role title is outside target CSE/software/AI engineering scope."

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


def normalize_job_title(title: str) -> str:
    """Normalize a title by stripping location suffixes like ' - Bangalore, India' or ' (Mumbai)'."""
    if not title:
        return ""
    cleaned = str(title).strip()
    # 1. Match ' - <Any City>, India/IN'
    cleaned = re.sub(r"\s*[-–—|/]\s*[A-Za-z\s]+,\s*(?:India|IN)\s*$", "", cleaned, flags=re.I)
    # 2. Match specific known cities / locations in suffixes or parentheses/brackets
    loc_tokens = (
        r"bangalore|bengaluru|mumbai|delhi|hyderabad|chennai|gurgaon|gurugram|noida|pune|"
        r"kolkata|kochi|ahmedabad|chandigarh|jaipur|indore|coimbatore|kerala|karnataka|india|remote"
    )
    cleaned = re.sub(rf"\s*[-–—|/]\s*(?:{loc_tokens}).*$", "", cleaned, flags=re.I)
    cleaned = re.sub(rf"\s*\((?:{loc_tokens})[^)]*\)", "", cleaned, flags=re.I)
    cleaned = re.sub(rf"\s*\[(?:{loc_tokens})[^\]]*\]", "", cleaned, flags=re.I)
    return cleaned.strip()


def deduplicate_multi_location_jobs(job_list: list[dict]) -> list[dict]:
    """Group duplicate postings across multiple cities/locations from the same company.

    Retains the highest-fit representative listing while collapsing location clones
    (e.g., Speechify in 8 Indian cities -> 'Bangalore (+7 locations)').
    """
    if not job_list:
        return []

    groups: dict[tuple[str, str], list[dict]] = {}
    for j in job_list:
        if not isinstance(j, dict):
            continue
        comp_key = company_classifier.normalize_company_key(j.get("company", ""))
        title_key = normalize_job_title(j.get("title", "")).lower()
        key = (comp_key, title_key)
        groups.setdefault(key, []).append(j)

    deduped = []
    for (comp_key, title_key), group in groups.items():
        if len(group) == 1:
            deduped.append(group[0])
            continue

        # Choose best candidate: highest score, prefer direct URL, prefer remote
        best_candidate = max(
            group,
            key=lambda x: (
                x.get("score") or 0,
                bool(x.get("job_url_direct")),
                is_job_truly_remote(x),
            )
        )
        rep = dict(best_candidate)
        rep["title"] = normalize_job_title(best_candidate.get("title", ""))

        # Collect distinct location strings
        locs = []
        for g in group:
            loc = (g.get("location") or "").strip()
            if loc and loc not in locs:
                locs.append(loc)

        if len(locs) > 1:
            first_loc = locs[0].split(",")[0].strip()
            other_cnt = len(locs) - 1
            rep["location"] = f"{first_loc} (+{other_cnt} locations)"

        deduped.append(rep)

    return deduped

