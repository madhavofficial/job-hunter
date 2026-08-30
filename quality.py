"""Additional job-quality rules for ranking and presentation.

The deterministic screening safeguards in ``screening.py`` remain unchanged. This
module adds a conservative presentation/matching policy: unknown aggregator
companies are not presented as verified Tier 1 companies, while jobs fetched from
official ATS sources remain eligible for Tier 1 discovery.
"""

import re

from screening import AGENCY_MARKERS, KNOWN_ENTERPRISES


KNOWN_PRODUCT_COMPANIES = {
    "anthropic", "openai", "postman", "razorpay", "zerodha", "swiggy",
    "zomato", "cred", "meesho", "phonepe", "flipkart", "browserbase",
    "sarvam ai", "microsoft", "google", "amazon", "stripe", "qualcomm",
    "ixigo", "fancode", "pocket fm", "galaxeye", "darwinbox", "freshworks",
}

LARGE_REPUTABLE_PRODUCT_COMPANIES = {
    "amazon", "anthropic", "flipkart", "freshworks", "google", "meesho",
    "microsoft", "openai", "phonepe", "postman", "razorpay", "stripe",
    "swiggy", "zerodha", "zomato",
}


def classify_job_tier(job: dict) -> str:
    """Classify a job conservatively using both company and source metadata."""
    company = (job.get("company") or "").strip().lower()
    source = (job.get("site") or "").strip().lower()

    if (
        not company
        or company in {"none", "confidential", "private limited", "company name"}
        or any(marker in company for marker in AGENCY_MARKERS)
    ):
        return "Tier 3: Staffing Agency / Unverified"
    # Match company aliases on word boundaries. A raw substring check mislabels
    # companies such as "TrustFabric" as "UST".
    if any(re.search(rf"\b{re.escape(name)}\b", company) for name in KNOWN_ENTERPRISES):
        return "Tier 2: Global Enterprise / IT Services"
    if company in KNOWN_PRODUCT_COMPANIES or source.startswith("ats:"):
        return "Tier 1: Product Company / AI Startup"
    return "Tier 3: Staffing Agency / Unverified"


def is_large_reputable_product_company(job: dict) -> bool:
    """Return whether a role belongs to a known large product company."""
    company = (job.get("company") or "").strip().lower()
    return any(re.search(rf"\b{re.escape(name)}\b", company) for name in LARGE_REPUTABLE_PRODUCT_COMPANIES)


def passes_shortlist_policy(job: dict, passes_hard_filters: bool, score: int) -> bool:
    """Apply the user-facing policy after hard filters and compatibility scoring."""
    if not passes_hard_filters:
        return False
    if is_large_reputable_product_company(job):
        return True
    return score >= 70


def has_usable_description(job: dict) -> bool:
    """Require enough listing text for a meaningful compatibility decision."""
    description = str(job.get("description") or "").strip().lower()
    return len(description) >= 120 and description not in {"nan", "none", "null"}


def is_reviewable_job(job: dict) -> bool:
    """Allow an unknown but concrete company into the clearly labeled review queue."""
    company = (job.get("company") or "").strip().lower()
    if not company or company in {"none", "confidential", "private limited", "company name"}:
        return False
    if any(marker in company for marker in AGENCY_MARKERS):
        return False
    return has_usable_description(job)


def apply_skill_gap_penalty(score: int, job: dict, resume_text: str) -> tuple[int, str | None]:
    """Cap scores when the job headline requires a technology absent from the resume."""
    title = (job.get("title") or "").lower()
    resume = (resume_text or "").lower()
    headline_only_skills = {
        "angular": "Angular",
        "typescript": "TypeScript",
        "vue": "Vue",
        ".net": ".NET",
        "c#": "C#",
        "golang": "Go",
        "rust": "Rust",
        "ruby": "Ruby",
        "php": "PHP",
    }
    missing = [label for token, label in headline_only_skills.items() if token in title and token not in resume]
    if not missing:
        return score, None
    capped_score = min(score, 68)
    return capped_score, f"Missing headline technology: {', '.join(missing)} is not present in the candidate resume."
