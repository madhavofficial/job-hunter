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
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
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


EXTERNAL_BOARD_FEEDS = (
    "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json",
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2025-Internships/dev/.github/scripts/listings.json",
)


def sync_external_board_feeds() -> int:
    """Dynamically discover tech company ATS boards from live open-source feeds."""
    discovered = set()

    # Open-source engineering feeds
    for feed_url in EXTERNAL_BOARD_FEEDS:
        try:
            req = Request(feed_url, headers={"User-Agent": "job-hunter/2.0"})
            with urlopen(req, timeout=12) as resp:
                data = json.load(resp)
            urls = [item.get("url") for item in data if isinstance(item, dict) and item.get("url")]
            found = discover_board_refs(urls)
            discovered.update(found)
        except Exception as exc:
            print(f"Notice: external feed sync notice for {feed_url}: {exc}", file=sys.stderr)

    if discovered:
        added = db.add_ats_boards(list(discovered), source="community_feed")
        print(f"✓ Dynamic Board Feed: Discovered {len(discovered)} boards ({added} newly registered).")
        return added
    return 0


class _DynamicBoardsTuple(tuple):
    """Dynamic board tuple that resolves from the database cache without hardcoded company lists."""
    def __contains__(self, item):
        boards = db.get_registered_ats_boards()
        if not boards:
            sync_external_board_feeds()
            boards = db.get_registered_ats_boards()
        return item in boards

    def __iter__(self):
        return iter(db.get_registered_ats_boards())

    def __len__(self):
        return len(db.get_registered_ats_boards())

CURATED_ATS_BOARDS = _DynamicBoardsTuple()


def is_target_engineering_title(title: str) -> bool:
    """Fast ATS pre-filter: rejects non-technical and senior/leadership titles early."""
    if not title or not isinstance(title, str):
        return False
    t = title.strip().lower()

    # Reject non-CSE / non-technical domains
    NON_TECH_KEYWORDS = (
        "sales", "marketing", "account executive", "account manager", "account director",
        "business development", "bdr", "sdr", "recruiter", "recruitment", "talent acquisition",
        "human resources", "people partner", "people operations", "legal", "counsel",
        "compliance", "financial analyst", "accountant", "finance manager", "controller",
        "payroll", "communications", "pr manager", "copywriter", "content writer",
        "graphic designer", "video editor", "office manager", "executive assistant",
        "customer success", "customer support", "workplace experience", "facilities",
        "policy",
    )
    for kw in NON_TECH_KEYWORDS:
        if kw in t:
            return False

    # Reject senior / leadership / executive level titles
    SENIOR_PATTERN = r"\b(?:senior|sr\.?|lead|principal|staff|manager|director|head of|vp|vice president|chief)\b"
    if re.search(SENIOR_PATTERN, t, re.I):
        return False

    return True


def _is_india_or_remote(location: str, is_remote: bool = False) -> bool:

    loc = (location or "").lower()
    # Check if explicitly in India or Indian cities/states/regions
    india_pattern = (
        r"\bindia\b|bengaluru|bangalore|hyderabad|pune|mumbai|delhi|noida|gurugram|gurgaon|"
        r"chennai|kolkata|ahmedabad|kochi|kerala|karnataka|tamil nadu|maharashtra|telangana|"
        r"gujarat|chandigarh|jaipur|indore|bhopal|coimbatore|trivandrum|thiruvananthapuram"
    )
    if re.search(india_pattern, loc):
        return True

    if is_remote or "remote" in loc:
        # Check if explicitly non-India remote (e.g. US, EMEA, AMER, etc.)
        non_india_regions = (
            r"\b(?:united states|u\.s\.a?\.?|usa|san francisco|new york|nyc|seattle|austin|"
            r"california|los angeles|chicago|london|berlin|paris|tokyo|toronto|canada|uk|"
            r"united kingdom|australia|sydney|singapore|germany|france|amer|emea|latam|belgrade)\b"
        )
        if re.search(non_india_regions, loc) and not re.search(r"\b(?:global|worldwide|anywhere|india)\b", loc):
            return False
        return True
    return False


def _greenhouse_jobs(board: str) -> list[dict]:
    payload = _fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true")
    jobs = []
    for item in payload.get("jobs", []):
        title = item.get("title", "")
        if not is_target_engineering_title(title):
            continue
        location = (item.get("location") or {}).get("name", "")
        is_remote = "remote" in location.lower()
        if not _is_india_or_remote(location, is_remote):
            continue
        jobs.append({
            "id": f"gh-{item['id']}", "site": "ats:greenhouse", "title": title,
            "company": board.replace("-", " ").title(), "location": location,
            "job_url": item.get("absolute_url", ""), "job_url_direct": item.get("absolute_url", ""),
            "date_posted": _date_value(item.get("updated_at")),
            "description": html_to_text(item.get("content")), "is_remote": is_remote,
            "skills": "", "experience_range": "",
        })
    return jobs


def _lever_jobs(board: str) -> list[dict]:
    payload = _fetch_json(f"https://api.lever.co/v0/postings/{board}?mode=json")
    jobs = []
    for item in payload if isinstance(payload, list) else []:
        title = item.get("text", "")
        if not is_target_engineering_title(title):
            continue
        categories = item.get("categories") or {}
        locations = categories.get("locations") or []
        location = "; ".join(locations) if isinstance(locations, list) else str(locations)
        is_remote = "remote" in location.lower() or "remote" in str(item.get("workplaceType", "")).lower()
        if not _is_india_or_remote(location, is_remote):
            continue
        jobs.append({
            "id": f"lever-{item.get('id')}", "site": "ats:lever", "title": title,
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
        title = item.get("title", "")
        if not is_target_engineering_title(title):
            continue
        locations = [item.get("location", "")] + [x.get("location", "") for x in item.get("secondaryLocations", [])]
        location = "; ".join(filter(None, locations))
        is_remote = bool(item.get("isRemote")) or "remote" in location.lower()
        if not _is_india_or_remote(location, is_remote):
            continue
        jobs.append({
            "id": f"ashby-{item.get('id')}", "site": "ats:ashby", "title": title,
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
    parsed_url = urlparse(url)
    clean_query = [(key, value) for key, value in parse_qsl(parsed_url.query) if not key.lower().startswith("utm_")]
    url = urlunparse(parsed_url._replace(query=urlencode(clean_query)))
    timeout = max(20, int(os.getenv("CAREER_PAGE_TIMEOUT_SECONDS", "45")))
    html = None
    last_error = None
    for attempt in range(2):
        try:
            request = Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            })
            with urlopen(request, timeout=timeout) as response:
                html = response.read().decode("utf-8", errors="replace")
            break
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(2)
    if html is None:
        print(f"Notice: career listing deferred after retries for {url}: {last_error}", file=sys.stderr)
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
    if not isinstance(address, dict):
        address = {}

    def _extract_addr_str(val):
        if isinstance(val, dict):
            return str(val.get("name") or val.get("@value") or "")
        if isinstance(val, list):
            return ", ".join(filter(None, [_extract_addr_str(x) for x in val]))
        return str(val).strip() if val is not None else ""

    locality = _extract_addr_str(address.get("addressLocality", ""))
    region = _extract_addr_str(address.get("addressRegion", ""))
    country = _extract_addr_str(address.get("addressCountry", ""))
    location = ", ".join(filter(None, [locality, region, country]))
    description = html_to_text(posting.get("description", ""))
    if not title:
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
        title = html_lib.unescape(title_match.group(1)).strip() if title_match else ""
    if not description:
        meta_match = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', html, flags=re.IGNORECASE | re.DOTALL)
        description = html_lib.unescape(meta_match.group(1)).strip() if meta_match else ""
    if not title or not company:
        return None
    if not is_target_engineering_title(title):
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
    # Use modern high-signal role terms rather than arbitrary slices
    keyword_query = '"Software Engineer" OR "AI Engineer" OR "Machine Learning" OR "Backend Developer" OR "Applied AI" OR "SDE"'
    urls = []
    try:
        provider = os.getenv("ATS_SEARCH_PROVIDER", "auto")
        print(f"Using dynamic ATS search provider: {provider}")
        for domain in ATS_HOSTS:
            query = f"site:{domain} ({keyword_query}) India OR remote"
            try:
                found = search_urls(query, count=15)
                urls.extend(found)
                time.sleep(0.5)
            except SearchRateLimitError as exc:
                print(f"Warning: ATS discovery stopped after provider rate limit: {exc}", file=sys.stderr)
                break
            except SearchProviderError as exc:
                print(f"Warning: ATS discovery failed for {domain}: {exc}", file=sys.stderr)
    except SearchProviderError as exc:
        print(f"Warning: ATS discovery unavailable: {exc}", file=sys.stderr)

    refs = discover_board_refs(urls)
    if refs:
        db.add_ats_boards(list(refs), source="search_dork")
    return urls


def discover_career_board_jobs(limit_per_domain: int = 50) -> pd.DataFrame:
    """Discover dynamic Workday/Oracle/other board listings via Google Jobs.

    These providers do not share one stable unauthenticated API. Querying the
    public index keeps discovery dynamic and avoids maintaining company slugs.
    A failure for one provider is isolated from the remaining domains.
    """
    keyword_query = '"Software Engineer" OR "AI Engineer" OR "Machine Learning" OR "Backend Developer" OR "Applied AI" OR "SDE"'
    rows = []
    try:
        provider = os.getenv("ATS_SEARCH_PROVIDER", "auto")
        print(f"Using dynamic career-board search provider: {provider}")
        for domain in CAREER_BOARD_DOMAINS:
            query = f"site:{domain} ({keyword_query}) India OR remote"
            try:
                urls = search_urls(query, count=min(limit_per_domain, 10))
                listings = []
                for url in urls:
                    try:
                        listing = _career_listing_from_url(url, domain)
                        if listing:
                            listings.append(listing)
                    except Exception as exc:
                        print(f"Warning: error parsing career listing from {url}: {exc}", file=sys.stderr)
                if listings:
                    rows.extend(listings)
                    print(f"Career discovery {domain}: {len(listings)} parsed listings.")
                time.sleep(0.5)
            except SearchRateLimitError as exc:
                print(f"Warning: career-board discovery stopped after provider rate limit: {exc}", file=sys.stderr)
                break
            except SearchProviderError as exc:
                print(f"Warning: career-board discovery failed for {domain}: {exc}", file=sys.stderr)
    except SearchProviderError as exc:
        print(f"Warning: career-board discovery unavailable: {exc}", file=sys.stderr)
    return pd.DataFrame(rows)


def run_ats_collector(batch_size: int = 200) -> int:
    import concurrent.futures
    from urllib.error import HTTPError

    db.init_db()
    total = 0

    print("\n====================================================")
    print("🚀 DYNAMIC DIRECT ATS INGESTION PIPELINE")
    print("====================================================")

    # 1. Dynamically sync board registries from live engineering feeds (zero hardcoding)
    print("Priority 1: Syncing tech company ATS boards from dynamic community feeds...", flush=True)
    sync_external_board_feeds()

    # 2. Retrieve registered active boards from persistent cache and scrape concurrently
    active_boards = db.get_registered_ats_boards(active_only=True, limit=batch_size)
    print(f"Priority 2: Concurrently scraping {len(active_boards)} registered ATS boards...", flush=True)

    def _scrape_board(item: tuple[str, str]) -> tuple[str, str, int, list[dict]]:
        ats, board = item
        try:
            jobs = fetch_board_jobs(ats, board)
            return (ats, board, 1, jobs)
        except HTTPError as e:
            is_active = 0 if e.code in (404, 410) else 1
            return (ats, board, is_active, [])
        except Exception:
            return (ats, board, 1, [])

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_scrape_board, b): b for b in active_boards}
        for future in concurrent.futures.as_completed(futures):
            ats, board, is_active, jobs = future.result()
            added = 0
            if jobs:
                added = db.add_jobs(pd.DataFrame(jobs))
                total += added
                print(f"✓ ATS {ats}/{board}: {len(jobs)} India/remote jobs ({added} new).", flush=True)
            db.update_ats_board_scraped(ats, board, len(jobs), is_active=is_active)

    # 3. Discover new India/Remote boards via live search index (incremental discovery)
    print("Priority 3: Discovering fresh ATS boards via search index...", flush=True)
    try:
        discover_ats_urls()
    except Exception as exc:
        print(f"Notice: search ATS discovery skipped: {exc}", file=sys.stderr)

    # 4. Discover Workday/Oracle career-board listings
    print("Priority 4: Discovering Workday/Oracle and enterprise career-board listings...", flush=True)
    try:
        career_jobs = discover_career_board_jobs()
        if not career_jobs.empty:
            added = db.add_jobs(career_jobs)
            total += added
            print(f"Dynamic career boards: {len(career_jobs)} indexed jobs, {added} new.", flush=True)
    except Exception as exc:
        print(f"Notice: career board discovery skipped: {exc}", file=sys.stderr)


    print(f"\n✅ Dynamic ATS collection complete. New direct jobs stored: {total}\n")
    return total



if __name__ == "__main__":
    run_ats_collector()
