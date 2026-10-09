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
from screening import is_india_or_worldwide as _is_india_or_remote, is_open_application_title
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
)

# Search is only a board index. Bare "remote" pulls US-remote copies, so the
# location clause stays India or explicitly worldwide.
INDIA_DISCOVERY_LOCATIONS = (
    '(India OR Bengaluru OR Bangalore OR Hyderabad OR Pune OR Mumbai OR Worldwide OR "Remote, Global")'
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
            from enterprise_boards import enterprise_refs_from_urls
            found.update(enterprise_refs_from_urls(urls))
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
    if is_open_application_title(t):
        return False

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


def company_name_from_listing(item: dict, board: str) -> str:
    """Prefer the employer name published by the ATS over the board slug."""
    if isinstance(item, dict):
        for key in ("company_name", "companyName", "organizationName"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return str(board or "").replace("-", " ").replace("_", " ").title()


def board_persist_fields(outcome: str, jobs_found: int, saw_india: bool, ats: str | None = None) -> tuple[int | None, int | None]:
    """Decide which board columns to write after a scrape.

    A transport error leaves job_count and is_active unchanged. A Greenhouse,
    Lever, or Ashby board with no India or worldwide role is deactivated so it
    stops consuming the batch. An enterprise tenant stays active: one day
    without a junior India opening is not evidence the company never hires there.
    A removed board (HTTP 404 or 410) is deactivated for every ATS.
    """
    if outcome == "ok" and jobs_found:
        return jobs_found, 1
    if outcome == "ok" and saw_india:
        return 0, 1
    if outcome == "ok":
        from enterprise_boards import ENTERPRISE_ATS
        if str(ats or "").lower() in ENTERPRISE_ATS:
            return 0, 1
        return 0, 0
    if outcome == "gone":
        return None, 0
    return None, None


# Every active enterprise board should be revisited about once a week.
# A board without India roles now costs one request, so the daily share can
# scale with the catalog. The cap bounds a run when the registry grows.
ENTERPRISE_CYCLE_DAYS = 7
ENTERPRISE_MIN_DAILY = 8
ENTERPRISE_MAX_DAILY = 300


def enterprise_daily_limit(active_boards: int) -> int:
    if active_boards <= 0:
        return 0
    share = -(-active_boards // ENTERPRISE_CYCLE_DAYS)
    return max(ENTERPRISE_MIN_DAILY, min(ENTERPRISE_MAX_DAILY, share))


def _join_location_parts(parts: list[str]) -> str:
    seen = []
    for part in parts:
        text = str(part or "").strip()
        if text and text not in seen:
            seen.append(text)
    return "; ".join(seen)


def _greenhouse_location(item: dict) -> str:
    parts = []
    name = ((item.get("location") or {}).get("name") or "").strip()
    if name:
        parts.append(name)
    for office in item.get("offices") or []:
        if isinstance(office, dict):
            office_name = str(office.get("name") or "").strip()
            if office_name:
                parts.append(office_name)
    return _join_location_parts(parts)


def _lever_location(item: dict) -> str:
    categories = item.get("categories") or {}
    parts = []
    location = categories.get("location")
    if isinstance(location, str) and location.strip():
        parts.append(location.strip())
    all_locations = categories.get("allLocations") or categories.get("locations") or []
    if isinstance(all_locations, str):
        all_locations = [all_locations]
    if isinstance(all_locations, list):
        parts.extend(str(value).strip() for value in all_locations if str(value or "").strip())
    country = str(item.get("country") or "").strip()
    if country:
        parts.append(country)
    return _join_location_parts(parts)


def _ashby_location(item: dict) -> str:
    parts = []
    primary = str(item.get("location") or "").strip()
    if primary:
        parts.append(primary)
    address = item.get("address") or {}
    postal = address.get("postalAddress") if isinstance(address, dict) else {}
    if isinstance(postal, dict):
        for key in ("addressLocality", "addressRegion", "addressCountry"):
            value = str(postal.get(key) or "").strip()
            if value:
                parts.append(value)
    for secondary in item.get("secondaryLocations") or []:
        if isinstance(secondary, dict):
            value = str(secondary.get("location") or "").strip()
        else:
            value = str(secondary or "").strip()
        if value:
            parts.append(value)
    return _join_location_parts(parts)


def _accept_role(title: str, location: str, is_remote: bool, record: dict, jobs: list[dict], saw_india: bool) -> bool:
    if not _is_india_or_remote(location, is_remote):
        return saw_india
    if is_target_engineering_title(title):
        jobs.append(record)
    return True


def _greenhouse_jobs(board: str) -> tuple[list[dict], bool]:
    payload = _fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true")
    jobs = []
    saw_india = False
    for item in payload.get("jobs", []):
        title = item.get("title", "")
        location = _greenhouse_location(item)
        is_remote = "remote" in location.lower()
        record = {
            "id": f"gh-{item['id']}", "site": "ats:greenhouse", "title": title,
            "company": company_name_from_listing(item, board), "location": location,
            "job_url": item.get("absolute_url", ""), "job_url_direct": item.get("absolute_url", ""),
            "date_posted": _date_value(item.get("updated_at")),
            "description": html_to_text(item.get("content")), "is_remote": is_remote,
            "skills": "", "experience_range": "",
        }
        saw_india = _accept_role(title, location, is_remote, record, jobs, saw_india)
    return jobs, saw_india


def _lever_jobs(board: str) -> tuple[list[dict], bool]:
    payload = _fetch_json(f"https://api.lever.co/v0/postings/{board}?mode=json")
    jobs = []
    saw_india = False
    for item in payload if isinstance(payload, list) else []:
        title = item.get("text", "")
        location = _lever_location(item)
        is_remote = "remote" in location.lower() or "remote" in str(item.get("workplaceType", "")).lower()
        record = {
            "id": f"lever-{item.get('id')}", "site": "ats:lever", "title": title,
            "company": company_name_from_listing(item, board), "location": location,
            "job_url": item.get("hostedUrl", ""), "job_url_direct": item.get("applyUrl") or item.get("hostedUrl", ""),
            "date_posted": _date_value(item.get("createdAt")),
            "description": item.get("descriptionPlain") or html_to_text(item.get("description")),
            "is_remote": is_remote, "skills": "", "experience_range": "",
        }
        saw_india = _accept_role(title, location, is_remote, record, jobs, saw_india)
    return jobs, saw_india


def _ashby_jobs(board: str) -> tuple[list[dict], bool]:
    payload = _fetch_json(f"https://api.ashbyhq.com/posting-api/job-board/{board}")
    jobs = []
    saw_india = False
    for item in payload.get("jobs", []) if isinstance(payload, dict) else []:
        title = item.get("title", "")
        location = _ashby_location(item)
        is_remote = bool(item.get("isRemote")) or "remote" in location.lower()
        record = {
            "id": f"ashby-{item.get('id')}", "site": "ats:ashby", "title": title,
            "company": company_name_from_listing(item, board), "location": location,
            "job_url": item.get("jobUrl", ""), "job_url_direct": item.get("applyUrl") or item.get("jobUrl", ""),
            "date_posted": _date_value(item.get("publishedAt") or item.get("updatedAt")),
            "description": html_to_text(item.get("descriptionHtml")) or item.get("descriptionPlain") or item.get("description", ""),
            "is_remote": is_remote, "skills": "", "experience_range": "",
        }
        saw_india = _accept_role(title, location, is_remote, record, jobs, saw_india)
    return jobs, saw_india


def fetch_board_observation(ats: str, board: str) -> tuple[list[dict], bool]:
    if ats == "greenhouse":
        return _greenhouse_jobs(board)
    if ats == "lever":
        return _lever_jobs(board)
    if ats == "ashby":
        return _ashby_jobs(board)
    from enterprise_boards import ENTERPRISE_ATS, fetch_enterprise_board
    if ats in ENTERPRISE_ATS:
        return fetch_enterprise_board(ats, board)
    raise ValueError(f"Unsupported ATS: {ats}")


def fetch_board_jobs(ats: str, board: str) -> list[dict]:
    jobs, _saw_india = fetch_board_observation(ats, board)
    return jobs


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
    if not _is_india_or_remote(location, "remote" in location.lower()):
        return None
    return {
        "id": f"career-{hashlib.sha1(url.encode()).hexdigest()[:16]}",
        "site": f"career:{domain}",
        "title": title,
        "company": company,
        "location": location,
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
            query = f"site:{domain} ({keyword_query}) {INDIA_DISCOVERY_LOCATIONS}"
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


# Search is only how an unknown tenant is learned. These hosts are the ones
# parse_enterprise_ref can turn into a board. Jobvite and Workable stay out
# because they have no native client yet.
ENTERPRISE_DISCOVERY_DOMAINS = (
    "myworkdayjobs.com",
    "myworkdaysite.com",
    "oraclecloud.com",
    "jobs.smartrecruiters.com",
    "taleo.net",
    "successfactors.com",
    "successfactors.eu",
    "sapsf.com",
    "sapsf.eu",
)


def discover_enterprise_boards() -> int:
    """Register Workday, Oracle, SAP, SmartRecruiters, and Taleo tenants from search.

    The search hit is discarded after the tenant URL is parsed. Job text comes
    from the platform API on a later scrape of that board.
    """
    from enterprise_boards import enterprise_refs_from_urls

    keyword_query = '"Software Engineer" OR "AI Engineer" OR "Machine Learning" OR "Backend Developer" OR "Applied AI" OR "SDE"'
    added = 0
    seen = set()
    try:
        provider = os.getenv("ATS_SEARCH_PROVIDER", "auto")
        print(f"Using search to discover enterprise career tenants: {provider}", flush=True)
        for domain in ENTERPRISE_DISCOVERY_DOMAINS:
            query = f"site:{domain} ({keyword_query}) {INDIA_DISCOVERY_LOCATIONS}"
            try:
                found = search_urls(query, count=15)
            except SearchRateLimitError as exc:
                print(f"Warning: enterprise board discovery stopped after provider rate limit: {exc}", file=sys.stderr)
                break
            except SearchProviderError as exc:
                print(f"Warning: enterprise board discovery failed for {domain}: {exc}", file=sys.stderr)
                continue
            refs = enterprise_refs_from_urls(found) - seen
            seen.update(refs)
            if refs:
                added += db.add_ats_boards(list(refs), source="search_dork")
            time.sleep(0.5)
    except SearchProviderError as exc:
        print(f"Warning: enterprise board discovery unavailable: {exc}", file=sys.stderr)
    if added:
        print(f"Registered {added} enterprise boards from search URLs.", flush=True)
    return added


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
            query = f"site:{domain} ({keyword_query}) {INDIA_DISCOVERY_LOCATIONS}"
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


def _scrape_registered_boards(boards: list[tuple[str, str]]) -> int:
    import concurrent.futures
    from urllib.error import HTTPError

    total = 0

    def _scrape_board(item: tuple[str, str]) -> tuple[str, str, str, list[dict], bool]:
        ats, board = item
        try:
            jobs, saw_india = fetch_board_observation(ats, board)
            return (ats, board, "ok", jobs, saw_india)
        except HTTPError as e:
            outcome = "gone" if e.code in (404, 410) else "error"
            return (ats, board, outcome, [], False)
        except Exception:
            return (ats, board, "error", [], False)

    deactivated = 0
    errors = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_scrape_board, b): b for b in boards}
        for future in concurrent.futures.as_completed(futures):
            ats, board, outcome, jobs, saw_india = future.result()
            added = 0
            if jobs:
                added = db.add_jobs(pd.DataFrame(jobs))
                total += added
                print(f"✓ ATS {ats}/{board}: {len(jobs)} India jobs ({added} new).", flush=True)
            job_count, is_active = board_persist_fields(outcome, len(jobs), saw_india, ats)
            if is_active == 0 and outcome == "ok":
                deactivated += 1
            elif outcome == "error":
                errors += 1
            db.update_ats_board_scraped(ats, board, job_count=job_count, is_active=is_active)
    print(
        f"Board sweep: {len(boards)} checked, {deactivated} deactivated with no India roles, {errors} temporary errors.",
        flush=True,
    )
    return total


def run_ats_collector(batch_size: int = 200) -> int:
    db.init_db()
    total = 0

    print("\n====================================================")
    print("🚀 DYNAMIC DIRECT ATS INGESTION PIPELINE")
    print("====================================================")

    # 1. Dynamically sync board registries from live engineering feeds (zero hardcoding)
    print("Priority 1: Syncing tech company ATS boards from dynamic community feeds...", flush=True)
    sync_external_board_feeds()
    from enterprise_boards import ENTERPRISE_ATS, seed_enterprise_boards_from_jobs
    restored = db.reactivate_enterprise_boards(ENTERPRISE_ATS)
    if restored:
        print(f"Restored {restored} enterprise boards that an empty India sweep had turned off.", flush=True)
    seeded = seed_enterprise_boards_from_jobs()
    print(f"Registered {seeded} enterprise career boards from stored listings.", flush=True)
    try:
        discover_enterprise_boards()
    except Exception as exc:
        print(f"Notice: enterprise board search skipped: {exc}", file=sys.stderr)

    # 2. Scrape enterprise boards on their own rotation so they are not stuck
    # behind the Greenhouse/Lever/Ashby backlog.
    enterprise_boards = []
    for ats_name in ENTERPRISE_ATS:
        limit = enterprise_daily_limit(db.count_registered_ats_boards(ats_name))
        if limit:
            enterprise_boards.extend(db.get_registered_ats_boards(active_only=True, limit=limit, ats=ats_name))
    if enterprise_boards:
        print(f"Priority 2: Scraping {len(enterprise_boards)} Workday/SmartRecruiters/Oracle/SAP/Taleo boards...", flush=True)
        total += _scrape_registered_boards(enterprise_boards)

    # 3. Retrieve registered active boards from persistent cache and scrape concurrently
    active_boards = db.get_registered_ats_boards(active_only=True, limit=batch_size)
    print(f"Priority 3: Concurrently scraping {len(active_boards)} registered ATS boards...", flush=True)
    total += _scrape_registered_boards(active_boards)

    # 4. Discover new Greenhouse/Lever/Ashby boards via the search index.
    print("Priority 4: Discovering fresh ATS boards via search index...", flush=True)
    try:
        discover_ats_urls()
    except Exception as exc:
        print(f"Notice: search ATS discovery skipped: {exc}", file=sys.stderr)

    print(f"\n✅ Dynamic ATS collection complete. New direct jobs stored: {total}\n")
    return total



if __name__ == "__main__":
    run_ats_collector()
