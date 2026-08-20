"""Dynamic discovery and ingestion of public Greenhouse, Lever, and Ashby boards.

Google Jobs is used only as a board-discovery index. Job data is fetched from the
official ATS JSON endpoints after an ATS URL is found.
"""

from __future__ import annotations

import html as html_lib
import json
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import pandas as pd
from jobspy import scrape_jobs

import db
from collector import get_dynamic_search_terms


ATS_HOSTS = {
    "jobs.ashbyhq.com": "ashby",
    "boards.greenhouse.io": "greenhouse",
    "job-boards.greenhouse.io": "greenhouse",
    "jobs.lever.co": "lever",
}


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


def discover_ats_urls() -> list[str]:
    terms = get_dynamic_search_terms()
    keyword_query = " OR ".join(f'"{term}"' for term in terms[:6])
    urls = []
    for domain in ATS_HOSTS:
        query = f"site:{domain} ({keyword_query}) India OR remote"
        try:
            results = scrape_jobs(
                site_name=["google"], google_search_term=query,
                location="India", results_wanted=50, country_indeed="india",
            )
            urls.extend(results.get("job_url", pd.Series(dtype=str)).dropna().tolist())
        except Exception as exc:
            print(f"Warning: ATS discovery failed for {domain}: {exc}", file=sys.stderr)
    return urls


def run_ats_collector() -> int:
    db.init_db()
    refs = discover_board_refs(discover_ats_urls())
    print(f"Discovered {len(refs)} ATS boards dynamically.")
    total = 0
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
