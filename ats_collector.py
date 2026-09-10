"""Dynamic discovery and ingestion of public Greenhouse, Lever, and Ashby boards.

Google Jobs is used only as a board-discovery index. Job data is fetched from the
official ATS JSON endpoints after an ATS URL is found.
"""

from __future__ import annotations

import html as html_lib
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import pandas as pd

import db
from collector import get_dynamic_search_terms
from search_provider import SearchProviderError, SearchRateLimitError, search_urls


ATS_HOSTS = {
    "jobs.ashbyhq.com": "ashby",
    "boards.greenhouse.io": "greenhouse",
    "job-boards.greenhouse.io": "greenhouse",
    "jobs.lever.co": "lever",
}

# These are public, indexable career-board hosts rather than a company
# allowlist. Google is used only to discover current listing URLs; the URL and
# company name returned by the listing are retained for direct application.
CAREER_BOARD_DOMAINS = (
    "myworkdayjobs.com",
    "taleo.net",
    "oraclecloud.com",
    "jobs.smartrecruiters.com",
    "jobs.jobvite.com",
    "apply.workable.com",
    "monster.com",
)


class _HTMLTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def text(self):
        return " ".join(" ".join(self.parts).split())


def html_to_text(value: str | None) -> str:
    parser = _HTMLTextParser()
    parser.feed(value or "")
    return html_lib.unescape(parser.text())


def discover_board_refs(urls: list[str]) -> set[tuple[str, str]]:
    """Extract unique (ATS, board slug) pairs from discovered ATS URLs."""
    refs = set()
    for url in urls:
        try:
            parsed = urlparse(url)
            host = parsed.netloc.lower().removeprefix("www.")
            ats = ATS_HOSTS.get(host)
            if not ats:
                continue
            parts = [part for part in parsed.path.split("/") if part]
            if parts:
                refs.add((ats, parts[0]))
        except ValueError:
            continue
    return refs


def _fetch_json(url: str) -> dict | list:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "job-hunter/1.0"})
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def _date_value(value):
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date().isoformat()
    return str(value)


def _is_india_or_remote(location: str, is_remote: bool = False) -> bool:
    if is_remote:
        return True
    location = (location or "").lower()
    return bool(re.search(r"\bindia\b|bengaluru|bangalore|hyderabad|pune|mumbai|delhi|noida|gurugram|chennai|kolkata", location))


def _greenhouse_jobs(board: str) -> list[dict]:
    payload = _fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true")
    jobs = []
    for item in payload.get("jobs", []):
        location = (item.get("location") or {}).get("name", "")
        if not _is_india_or_remote(location):
            continue
        jobs.append({
            "id": f"gh-{item['id']}", "site": "ats:greenhouse", "title": item.get("title", ""),
            "company": board.replace("-", " ").title(), "location": location,
            "job_url": item.get("absolute_url", ""), "job_url_direct": item.get("absolute_url", ""),
            "date_posted": _date_value(item.get("updated_at")),
            "description": html_to_text(item.get("content")), "is_remote": "remote" in location.lower(),
            "skills": "", "experience_range": "",
        })
    return jobs


def _lever_jobs(board: str) -> list[dict]:
    payload = _fetch_json(f"https://api.lever.co/v0/postings/{board}?mode=json")
    jobs = []
    for item in payload if isinstance(payload, list) else []:
        categories = item.get("categories") or {}
        locations = categories.get("locations") or []
        location = "; ".join(locations) if isinstance(locations, list) else str(locations)
        is_remote = "remote" in location.lower() or "remote" in str(item.get("workplaceType", "")).lower()
        if not _is_india_or_remote(location, is_remote):
            continue
        jobs.append({
            "id": f"lever-{item.get('id')}", "site": "ats:lever", "title": item.get("text", ""),
            "company": board.replace("-", " ").title(), "location": location,
            "job_url": item.get("hostedUrl", ""), "job_url_direct": item.get("applyUrl") or item.get("hostedUrl", ""),
            "date_posted": _date_value(item.get("createdAt")),
            "description": item.get("descriptionPlain") or html_to_text(item.get("description")),
            "is_remote": is_remote, "skills": "", "experience_range": "",
        })
    return jobs


def _ashby_jobs(board: str) -> list[dict]:
    payload = _fetch_json(f"https://api.ashbyhq.com/posting-api/job-board/{board}")
    jobs = []
    for item in payload.get("jobs", []) if isinstance(payload, dict) else []:
        locations = [item.get("location", "")] + [x.get("location", "") for x in item.get("secondaryLocations", [])]
        location = "; ".join(filter(None, locations))
        is_remote = bool(item.get("isRemote")) or "remote" in location.lower()
        if not _is_india_or_remote(location, is_remote):
            continue
        jobs.append({
            "id": f"ashby-{item.get('id')}", "site": "ats:ashby", "title": item.get("title", ""),
            "company": board.replace("-", " ").title(), "location": location,
            "job_url": item.get("jobUrl", ""), "job_url_direct": item.get("applyUrl") or item.get("jobUrl", ""),
            "date_posted": _date_value(item.get("publishedAt") or item.get("updatedAt")),
            "description": html_to_text(item.get("descriptionHtml")) or item.get("description", ""),
            "is_remote": is_remote, "skills": "", "experience_range": "",
        })
    return jobs


def fetch_board_jobs(ats: str, board: str) -> list[dict]:
    if ats == "greenhouse":
        return _greenhouse_jobs(board)
    if ats == "lever":
        return _lever_jobs(board)
    if ats == "ashby":
        return _ashby_jobs(board)
    raise ValueError(f"Unsupported ATS: {ats}")


def _career_listing_from_url(url: str, domain: str) -> dict | None:
    """Extract common JobPosting JSON-LD fields from a public career page."""
    try:
        request = Request(url, headers={"User-Agent": "job-hunter/1.0"})
        with urlopen(request, timeout=20) as response:
            html = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        print(f"Warning: career listing fetch failed for {url}: {exc}", file=sys.stderr)
        return None

    postings = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    posting = {}
    for raw in postings:
        try:
            payload = json.loads(html_lib.unescape(raw.strip()))
        except json.JSONDecodeError:
            continue
        candidates = payload if isinstance(payload, list) else payload.get("@graph", []) if isinstance(payload, dict) else []
        if isinstance(payload, dict) and payload.get("@type") == "JobPosting":
            candidates = [payload]
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
                posting = candidate
                break
        if posting:
            break

    title = posting.get("title", "")
    company_data = posting.get("hiringOrganization") or {}
    company = company_data.get("name", "") if isinstance(company_data, dict) else str(company_data)
    location_data = posting.get("jobLocation") or {}
    if isinstance(location_data, list):
        location_data = location_data[0] if location_data else {}
    address = location_data.get("address") if isinstance(location_data, dict) else {}
    location = address.get("addressLocality", "") if isinstance(address, dict) else ""
    location = ", ".join(filter(None, [location, address.get("addressRegion", "") if isinstance(address, dict) else "", address.get("addressCountry", "") if isinstance(address, dict) else ""]))
    description = html_to_text(posting.get("description", ""))
    if not title:
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
        title = html_lib.unescape(title_match.group(1)).strip() if title_match else ""
    if not description:
        meta_match = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', html, flags=re.IGNORECASE | re.DOTALL)
        description = html_lib.unescape(meta_match.group(1)).strip() if meta_match else ""
    if not title or not company:
        return None
    return {
        "id": f"career-{hashlib.sha1(url.encode()).hexdigest()[:16]}",
        "site": f"career:{domain}",
        "title": title,
        "company": company,
        "location": location or "India / Remote",
        "job_url": url,
        "job_url_direct": url,
        "date_posted": posting.get("datePosted", ""),
        "description": description,
        "is_remote": "remote" in location.lower(),
        "skills": "",
        "experience_range": "",
    }


def discover_ats_urls() -> list[str]:
    terms = get_dynamic_search_terms()
    keyword_query = " OR ".join(f'"{term}"' for term in terms[:6])
    urls = []
    try:
        provider = os.getenv("ATS_SEARCH_PROVIDER", "auto")
        print(f"Using dynamic ATS search provider: {provider}")
        for domain in ATS_HOSTS:
            query = f"site:{domain} ({keyword_query}) India OR remote"
            try:
                urls.extend(search_urls(query, count=10))
                time.sleep(1.0)
            except SearchRateLimitError as exc:
                print(f"Warning: ATS discovery stopped after provider rate limit: {exc}", file=sys.stderr)
                break
            except SearchProviderError as exc:
                print(f"Warning: ATS discovery failed for {domain}: {exc}", file=sys.stderr)
    except SearchProviderError as exc:
        print(f"Warning: ATS discovery unavailable: {exc}", file=sys.stderr)
    return urls


def discover_career_board_jobs(limit_per_domain: int = 50) -> pd.DataFrame:
    """Discover dynamic Workday/Oracle/other board listings via Google Jobs.

    These providers do not share one stable unauthenticated API. Querying the
    public index keeps discovery dynamic and avoids maintaining company slugs.
    A failure for one provider is isolated from the remaining domains.
    """
    terms = get_dynamic_search_terms()
    keyword_query = " OR ".join(f'"{term}"' for term in terms[:6])
    rows = []
    try:
        provider = os.getenv("ATS_SEARCH_PROVIDER", "auto")
        print(f"Using dynamic career-board search provider: {provider}")
        for domain in CAREER_BOARD_DOMAINS:
            query = f"site:{domain} ({keyword_query}) India OR remote"
            try:
                urls = search_urls(query, count=min(limit_per_domain, 10))
                listings = [listing for url in urls if (listing := _career_listing_from_url(url, domain))]
                if listings:
                    rows.extend(listings)
                    print(f"Career discovery {domain}: {len(listings)} parsed listings.")
                time.sleep(1.0)
            except SearchRateLimitError as exc:
                print(f"Warning: career-board discovery stopped after provider rate limit: {exc}", file=sys.stderr)
                break
            except SearchProviderError as exc:
                print(f"Warning: career-board discovery failed for {domain}: {exc}", file=sys.stderr)
    except SearchProviderError as exc:
        print(f"Warning: career-board discovery unavailable: {exc}", file=sys.stderr)
    return pd.DataFrame(rows)


def run_ats_collector() -> int:
    db.init_db()
    total = 0

    # Prioritize the career systems most commonly used by large employers.
    # This also lets direct Workday/Oracle records win canonical deduplication
    # before broader ATS sources are ingested.
    print("Priority 1: Discovering Workday/Oracle and other career-board listings...")
    career_jobs = discover_career_board_jobs()
    if not career_jobs.empty:
        added = db.add_jobs(career_jobs)
        total += added
        print(f"Dynamic career boards: {len(career_jobs)} indexed jobs, {added} new.")

    print("Priority 2: Discovering Ashby, Greenhouse, and Lever boards...")
    refs = discover_board_refs(discover_ats_urls())
    print(f"Discovered {len(refs)} ATS boards dynamically.")
    for ats, board in sorted(refs):
        try:
            jobs = fetch_board_jobs(ats, board)
            added = db.add_jobs(pd.DataFrame(jobs)) if jobs else 0
            total += added
            print(f"ATS {ats}/{board}: {len(jobs)} India/remote jobs, {added} new.")
        except Exception as exc:
            print(f"Warning: ATS board {ats}/{board} failed: {exc}", file=sys.stderr)
    print(f"ATS collection complete. New direct jobs stored: {total}")
    return total


if __name__ == "__main__":
    run_ats_collector()
