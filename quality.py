"""Deterministic listing-quality assessment and canonicalization helpers."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse


GENERIC_TITLES = {
    "software engineer",
    "software developer",
    "developer",
    "engineer",
    "technical intern",
    "intern",
}

IRRELEVANT_TITLE_MARKERS = (
    "php",
    "laravel",
    "ms access",
    "access developer",
    "business development",
    "sales",
    "marketing",
    "hr ",
    "human resources",
    "network security",
    "office it administrator",
)

TRUNCATION_MARKERS = (
    "description was truncated",
    "job description unavailable",
    "description unavailable",
    "no description",
    "show more jobs like this",
    "similar jobs",
)

AGGREGATOR_HOSTS = {
    "linkedin.com",
    "indeed.com",
    "naukri.com",
    "monster.com",
}


def normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def canonical_company(value: str) -> str:
    text = normalize_text(value)
    for suffix in (" private limited", " pvt ltd", " pvt limited", " limited", " ltd", " inc", " llc"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text


def canonical_title(value: str) -> str:
    text = normalize_text(value)
    text = re.sub(r"\b(?:i|ii|iii|iv|v|1|2|3)\b", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def canonical_job_key(job: dict) -> str:
    return f"{canonical_company(job.get('company'))}|{canonical_title(job.get('title'))}"


def host_for(job: dict) -> str:
    url = job.get("job_url_direct") or job.get("job_url") or ""
    return urlparse(url).netloc.lower().removeprefix("www.")


def has_direct_employer_signal(job: dict) -> bool:
    site = str(job.get("site") or "").lower()
    host = host_for(job)
    if site.startswith("ats:"):
        return True
    if host and not any(host == domain or host.endswith(f".{domain}") for domain in AGGREGATOR_HOSTS):
        return True
    return False


def description_quality(job: dict) -> tuple[int, str, str]:
    description = str(job.get("description") or "").strip()
    lowered = description.lower()
    if not description:
        return 0, "missing", "No job description was available."
    if any(marker in lowered for marker in TRUNCATION_MARKERS):
        return 20, "partial", "The listing description is truncated or only exposes aggregator metadata."
    if len(description) < 240:
        return 35, "partial", "The listing has too little description evidence to validate the match."
    if len(description) < 700:
        return 65, "partial", "The listing has only partial description evidence."
    return 100, "full", "The listing contains a sufficiently detailed job description."


def assess_listing_quality(job: dict, company_tier: str, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    title = normalize_text(job.get("title"))
    description_score, description_state, description_reason = description_quality(job)
    company = canonical_company(job.get("company"))
    direct = has_direct_employer_signal(job)

    if company_tier.startswith("Tier 1"):
        company_score = 100
    elif company_tier.startswith("Tier 2"):
        company_score = 80
    else:
        company_score = 20

    date_value = str(job.get("date_posted") or job.get("created_at") or "")[:19]
    freshness_score = 35
    try:
        posted = datetime.fromisoformat(date_value.replace("Z", ""))
        age = now - posted
        if age <= timedelta(days=2):
            freshness_score = 100
        elif age <= timedelta(days=7):
            freshness_score = 70
        elif age <= timedelta(days=14):
            freshness_score = 45
        else:
            freshness_score = 20
    except ValueError:
        pass

    role_evidence = 0
    searchable = f"{job.get('title') or ''}\n{job.get('description') or ''}\n{job.get('skills') or ''}".lower()
    if re.search(r"\b(?:software|backend|full.?stack|ai|ml|machine learning|data|python|java|cloud|devops|api)\b", searchable):
        role_evidence += 40
    if job.get("skills") or re.search(r"\b(?:python|java|javascript|react|node|pytorch|sql|fastapi)\b", searchable):
        role_evidence += 30
    if job.get("experience_range") or re.search(r"\b(?:intern|junior|entry|graduate|0\s*[-to]\s*2|years?)\b", searchable):
        role_evidence += 30
    evidence_score = min(100, role_evidence)

    generic_title = title in GENERIC_TITLES
    irrelevant = any(marker in title for marker in IRRELEVANT_TITLE_MARKERS)
    unknown_company = not company or company in {"none", "confidential", "company name", "custom opportunity"}
    directness_score = 100 if direct else 55

    reasons = [description_reason]
    if generic_title:
        reasons.append("The title is generic and needs strong description evidence.")
    if irrelevant:
        reasons.append("The title is outside the target software/AI role scope.")
    if not direct:
        reasons.append("No direct employer or ATS signal was found.")
    if unknown_company:
        reasons.append("The employer identity is unclear.")

    return {
        "company_score": company_score,
        "description_score": description_score,
        "evidence_score": evidence_score,
        "freshness_score": freshness_score,
        "directness_score": directness_score,
        "description_state": description_state,
        "generic_title": generic_title,
        "irrelevant_title": irrelevant,
        "direct_employer_signal": direct,
        "canonical_key": canonical_job_key(job),
        "reason": " ".join(reasons),
    }


def quality_gate(job: dict, company_tier: str, quality: dict | None = None) -> tuple[bool, str | None]:
    quality = quality or assess_listing_quality(job, company_tier)
    if company_tier.startswith("Tier 3"):
        return False, "Employer is unverified, anonymous, or appears to be a staffing/consulting source."
    if quality["description_score"] == 0:
        return False, "Missing job description; title-only inference is not reliable enough to shortlist."
    if quality["description_state"] == "partial" and quality["generic_title"]:
        return False, "Generic title with partial description evidence."
    if quality["irrelevant_title"]:
        return False, "Role title is outside the target software/AI scope."
    if quality["evidence_score"] < 40:
        return False, "Listing does not provide enough explicit role or eligibility evidence."
    return True, None


def weighted_match_score(role_fit: int, quality: dict) -> tuple[int, dict]:
    """Combine model role fit with auditable non-model quality components."""
    role_fit = max(0, min(100, int(role_fit)))
    evidence = quality["description_score"]
    company = quality["company_score"]
    freshness = quality["freshness_score"]
    directness = quality["directness_score"]
    final = round(role_fit * 0.55 + company * 0.20 + evidence * 0.15 + freshness * 0.05 + directness * 0.05)
    if evidence < 80:
        final = min(final, 79)
    if not quality["direct_employer_signal"]:
        final = min(final, 84)
    components = {
        "role_fit": role_fit,
        "company_quality": company,
        "evidence_quality": evidence,
        "freshness": freshness,
        "directness": directness,
        "final_score": final,
    }
    return final, components


def components_json(components: dict) -> str:
    return json.dumps(components, sort_keys=True)
