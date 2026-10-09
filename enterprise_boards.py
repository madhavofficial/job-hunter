"""Direct enterprise career-board clients.

Workday, SmartRecruiters, Oracle Cloud, SAP SuccessFactors (careerN /
sapsf hosts), and Taleo are fetched from each platform's public posting
endpoint. Search is not used to read the job.
"""

from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

import db
from screening import is_india_or_worldwide

ENTERPRISE_ATS = ("workday", "smartrecruiters", "oracle", "sap", "taleo")

_MAX_LIST_PAGES = 8
_MAX_DETAILS = 25
_LOCALE = re.compile(r"^[a-z]{2}(?:-[a-z]{2})?$")
_SAP_JOB = re.compile(r"<Job>(.*?)</Job>", re.S)


def _request(url: str, payload: dict | None = None, accept: str = "application/json") -> bytes:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Accept": accept, "User-Agent": "job-hunter/1.0"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method="POST" if payload is not None else "GET")
    with urlopen(request, timeout=25) as response:
        return response.read()


def _request_json(url: str, payload: dict | None = None):
    return json.loads(_request(url, payload=payload).decode("utf-8", errors="replace"))


def _join_location(parts: list[str]) -> str:
    seen = []
    for part in parts:
        text = str(part or "").strip()
        if text and text not in seen:
            seen.append(text)
    return "; ".join(seen)


def _text(value: str | None) -> str:
    from ats_collector import html_to_text
    return html_to_text(value or "")


def _keep(title: str, location: str, is_remote: bool) -> bool:
    from ats_collector import is_target_engineering_title
    return is_india_or_worldwide(location, is_remote) and is_target_engineering_title(title)


def _record(job_id: str, site: str, title: str, company: str, location: str, url: str, description: str, is_remote: bool, date_posted: str = "") -> dict:
    return {
        "id": job_id,
        "site": site,
        "title": title,
        "company": company,
        "location": location,
        "job_url": url,
        "job_url_direct": url,
        "date_posted": date_posted,
        "description": description,
        "is_remote": is_remote,
        "skills": "",
        "experience_range": "",
    }


def parse_enterprise_ref(url: str) -> tuple[str, str] | None:
    """Return (ats, board slug) when the URL identifies a whole career board."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = parsed.netloc.lower().removeprefix("www.")
    parts = [part for part in parsed.path.split("/") if part]
    query = {key.lower(): value for key, value in parse_qs(parsed.query).items()}

    if host == "jobs.smartrecruiters.com" and parts:
        return ("smartrecruiters", parts[0].lower())

    if host.endswith(".myworkdayjobs.com") and parts:
        body = parts[1:] if _LOCALE.match(parts[0].lower()) else parts
        if body and body[0].lower() != "job":
            return ("workday", f"{host}/{body[0].lower()}")

    if host.endswith(".myworkdaysite.com") and len(parts) >= 3 and parts[0].lower() == "recruiting":
        return ("workday", f"{host}/{parts[1].lower()}/{parts[2].lower()}")

    if host.endswith(".oraclecloud.com"):
        for index, part in enumerate(parts):
            if part.lower() == "sites" and index + 1 < len(parts):
                return ("oracle", f"{host}/{parts[index + 1].lower()}")

    if host.endswith(".taleo.net"):
        for index, part in enumerate(parts):
            if part.lower() == "careersection" and index + 1 < len(parts) and parts[index + 1].isdigit():
                return ("taleo", f"{host}/{parts[index + 1]}")

    if host.endswith((".successfactors.com", ".successfactors.eu", ".sapsf.com", ".sapsf.eu")):
        company = (query.get("company") or [""])[0].strip().lower()
        if company:
            return ("sap", f"{host}/{company}")
    return None


def enterprise_refs_from_urls(urls: list[str]) -> set[tuple[str, str]]:
    refs = set()
    for url in urls:
        ref = parse_enterprise_ref(url or "")
        if ref:
            refs.add(ref)
    return refs


def _remember(title: str, location: str, is_remote: bool, record: dict, jobs: list[dict], saw_india: bool) -> bool:
    if not is_india_or_worldwide(location, is_remote):
        return saw_india
    from ats_collector import is_target_engineering_title
    if is_target_engineering_title(title):
        jobs.append(record)
    return True


def _smartrecruiters_jobs(company: str) -> tuple[list[dict], bool]:
    jobs = []
    saw_india = False
    details = 0
    offset = 0
    while offset < _MAX_LIST_PAGES * 100:
        payload = _request_json(
            f"https://api.smartrecruiters.com/v1/companies/{company}/postings?limit=100&offset={offset}&country=in"
        )
        content = payload.get("content") or []
        if not content:
            break
        for item in content:
            title = item.get("name") or ""
            location_info = item.get("location") or {}
            location = _join_location([
                location_info.get("fullLocation") or "",
                location_info.get("city") or "",
                location_info.get("region") or "",
                location_info.get("country") or "",
            ])
            is_remote = bool(location_info.get("remote"))
            if not _keep(title, location, is_remote):
                if is_india_or_worldwide(location, is_remote):
                    saw_india = True
                continue
            if details >= _MAX_DETAILS:
                saw_india = True
                continue
            posting_id = str(item.get("id") or item.get("uuid") or "")
            detail = _request_json(f"https://api.smartrecruiters.com/v1/companies/{company}/postings/{posting_id}")
            details += 1
            sections = (detail.get("jobAd") or {}).get("sections") or {}
            description = _text("\n".join(
                str((sections.get(key) or {}).get("text") or "")
                for key in ("jobDescription", "qualifications", "additionalInformation")
            ))
            company_info = detail.get("company") or item.get("company") or {}
            company_name = company_info.get("name") if isinstance(company_info, dict) else company
            url = detail.get("postingUrl") or f"https://jobs.smartrecruiters.com/{company}/{posting_id}"
            record = _record(
                f"sr-{company}-{posting_id}", "ats:smartrecruiters", title,
                company_name or company, location, url, description, is_remote,
                str(detail.get("releasedDate") or item.get("releasedDate") or "")[:10],
            )
            saw_india = _remember(title, location, is_remote, record, jobs, saw_india)
        offset += len(content)
        if offset >= int(payload.get("totalFound") or 0):
            break
    return jobs, saw_india


def _workday_endpoint(slug: str) -> str:
    host, _, rest = slug.partition("/")
    if host.endswith(".myworkdaysite.com"):
        return f"https://{host}/wday/cxs/{rest}/jobs"
    tenant = host.split(".")[0]
    return f"https://{host}/wday/cxs/{tenant}/{rest}/jobs"


def _workday_location(info: dict, fallback: str) -> str:
    country = info.get("country")
    if isinstance(country, dict):
        country = country.get("descriptor") or country.get("alpha2Code") or ""
    return _join_location([fallback, str(info.get("location") or ""), str(country or "")])


def _flatten_workday_facets(facets: list, parent: str | None = None) -> list[tuple[str, str, int, str]]:
    values = []
    for facet in facets or []:
        param = facet.get("facetParameter") or parent
        for value in facet.get("values") or []:
            if "values" in value:
                values.extend(_flatten_workday_facets([value], param))
            elif param and value.get("id"):
                values.append((param, str(value.get("descriptor") or ""), int(value.get("count") or 0), value["id"]))
    return values


def workday_india_filter(facets: list) -> dict | None:
    """Pick one location facet whose values cover India or worldwide roles.

    Returns {} when the board has location facets and none of them is India,
    so the caller can stop after one request. Returns None when the board
    exposes no location facet, so the caller falls back to text search.
    Values inside one facet are OR-ed by Workday; two facets would be AND-ed,
    so only one parameter is used. A country-level "India" value wins.
    """
    values = _flatten_workday_facets(facets)
    location_values = [value for value in values if "location" in value[0].lower()]
    if not location_values:
        return None
    for param, descriptor, _count, value_id in location_values:
        if descriptor.strip().lower() == "india":
            return {param: [value_id]}
    by_param: dict[str, list[tuple[int, str]]] = {}
    for param, descriptor, count, value_id in location_values:
        if is_india_or_worldwide(descriptor, False):
            by_param.setdefault(param, []).append((count, value_id))
    if not by_param:
        return {}
    param, matches = max(by_param.items(), key=lambda item: sum(count for count, _ in item[1]))
    return {param: [value_id for _count, value_id in matches]}


def _workday_jobs(slug: str) -> tuple[list[dict], bool]:
    endpoint = _workday_endpoint(slug)
    jobs = []
    saw_india = False
    seen = set()
    details = 0
    probe = _request_json(endpoint, {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""})
    india_filter = workday_india_filter(probe.get("facets") or [])
    if india_filter == {}:
        return jobs, False
    if india_filter:
        queries = [(india_filter, "")]
    else:
        queries = [({}, search) for search in ("India", "Bengaluru", "Bangalore", "Hyderabad", "Pune", "Mumbai", "Remote")]
    for applied, search in queries:
        for page in range(_MAX_LIST_PAGES):
            payload = _request_json(endpoint, {"appliedFacets": applied, "limit": 20, "offset": page * 20, "searchText": search})
            postings = payload.get("jobPostings") or []
            if not postings:
                break
            if applied:
                saw_india = True
            for item in postings:
                path = item.get("externalPath") or ""
                if not path or path in seen:
                    continue
                seen.add(path)
                title = item.get("title") or ""
                listed_location = item.get("locationsText") or ""
                from ats_collector import is_target_engineering_title
                if not is_target_engineering_title(title):
                    if is_india_or_worldwide(listed_location, "remote" in listed_location.lower()):
                        saw_india = True
                    continue
                if details >= _MAX_DETAILS:
                    saw_india = saw_india or is_india_or_worldwide(listed_location, False)
                    continue
                detail = _request_json(endpoint.removesuffix("/jobs") + path)
                details += 1
                info = detail.get("jobPostingInfo") or {}
                location = _workday_location(info, listed_location)
                is_remote = "remote" in location.lower()
                org = detail.get("hiringOrganization") or {}
                company = org.get("name") if isinstance(org, dict) else ""
                url = info.get("externalUrl") or f"https://{slug.split('/')[0]}{path}"
                description = _text(info.get("jobDescription"))
                record = _record(
                    "wd-" + hashlib.sha1(url.encode()).hexdigest()[:16],
                    "ats:workday", info.get("title") or title, company or slug.split(".")[0],
                    location, url, description, is_remote, str(info.get("startDate") or "")[:10],
                )
                saw_india = _remember(record["title"], location, is_remote, record, jobs, saw_india)
            if len(postings) < 20:
                break
    return jobs, saw_india


def _oracle_site_number(site: str) -> str:
    if site.lower().startswith("cx_"):
        return "CX_" + site[3:]
    return site


def _oracle_jobs(slug: str) -> tuple[list[dict], bool]:
    host, _, site = slug.partition("/")
    site_number = _oracle_site_number(site)
    jobs = []
    saw_india = False
    details = 0
    for page in range(_MAX_LIST_PAGES):
        url = (
            f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
            f"?onlyData=true&expand=requisitionList.secondaryLocations"
            f"&finder=findReqs;siteNumber={site_number},limit=25,offset={page * 25}"
        )
        payload = _request_json(url)
        requisitions = []
        for item in payload.get("items") or []:
            requisitions.extend(item.get("requisitionList") or [])
        if not requisitions:
            break
        for item in requisitions:
            title = item.get("Title") or ""
            extra = []
            for bucket in (item.get("secondaryLocations") or []):
                if isinstance(bucket, dict):
                    extra.append(str(bucket.get("Name") or bucket.get("LocationName") or ""))
            location = _join_location([
                item.get("PrimaryLocation") or "",
                item.get("PrimaryLocationCountry") or "",
                *extra,
            ])
            is_remote = "remote" in location.lower()
            if not _keep(title, location, is_remote):
                if is_india_or_worldwide(location, is_remote):
                    saw_india = True
                continue
            if details >= _MAX_DETAILS:
                saw_india = True
                continue
            req_id = str(item.get("Id") or "")
            detail_url = (
                f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
                f"?onlyData=true&expand=all&finder=ById;Id=%22{req_id}%22,siteNumber={site_number}"
            )
            detail_items = (_request_json(detail_url).get("items") or [{}])
            detail = detail_items[0] if detail_items else {}
            details += 1
            description = _text("\n".join(str(detail.get(key) or item.get(key) or "") for key in (
                "ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr", "ShortDescriptionStr",
            )))
            apply_url = f"https://{host}/hcmUI/CandidateExperience/en/sites/{site_number}/job/{req_id}"
            record = _record(
                f"oracle-{host}-{req_id}", "ats:oracle", title, host.split(".")[0],
                location, apply_url, description, is_remote,
                str(detail.get("ExternalPostedStartDate") or item.get("PostedDate") or "")[:10],
            )
            saw_india = _remember(title, location, is_remote, record, jobs, saw_india)
        if len(requisitions) < 25:
            break
    return jobs, saw_india


def _sap_tag(block: str, tag: str) -> str:
    match = re.search(rf"<{tag}>(?:<!\[CDATA\[(.*?)\]\]>|([^<]*))</{tag}>", block, re.S)
    if not match:
        return ""
    return match.group(1) if match.group(1) is not None else (match.group(2) or "")


def sap_jobs_from_xml(xml_text: str, host: str, company: str) -> tuple[list[dict], bool]:
    jobs = []
    saw_india = False
    for block in _SAP_JOB.findall(xml_text):
        title = _sap_tag(block, "JobTitle")
        description = _text(_sap_tag(block, "Job-Description"))
        # SuccessFactors marketing copy uses "global" without naming a place.
        # Keep a row only when the posting itself names India.
        location = "India" if _india_named(f"{title}\n{description}") else ""
        req_id = _sap_tag(block, "ReqId") or hashlib.sha1(title.encode()).hexdigest()[:10]
        url = f"https://{host}/career?company={company}&career_ns=job_listing&career_job_req_id={req_id}"
        record = _record(
            f"sap-{company}-{req_id}", "ats:sap", title, company,
            location, url, description, "remote" in description.lower()[:400],
            _sap_tag(block, "Posted-Date"),
        )
        saw_india = _remember(title, location, record["is_remote"], record, jobs, saw_india)
    return jobs, saw_india


def _india_named(text: str) -> bool:
    cleaned = re.sub(r"\b(?:global|worldwide|anywhere)\b", " ", text or "", flags=re.I)
    return is_india_or_worldwide(cleaned, False)


def _sap_jobs(slug: str) -> tuple[list[dict], bool]:
    host, _, company = slug.partition("/")
    url = f"https://{host}/career?company={company}&career_ns=job_listing_summary&resultType=XML&rcm_site_locale=en_US"
    xml_text = _request(url, accept="application/xml,text/xml,*/*").decode("utf-8", errors="replace")
    return sap_jobs_from_xml(xml_text, host, company)


def _taleo_jobs(slug: str) -> tuple[list[dict], bool]:
    host, _, portal = slug.partition("/")
    sitemap = _request(
        f"https://{host}/careersection/sitemap.jss?portalCode={portal}&lang=en",
        accept="application/xml,text/xml,*/*",
    ).decode("utf-8", errors="replace")
    job_ids = re.findall(r"job=(\d+)", sitemap)
    jobs = []
    saw_india = False
    fetched = 0
    matched_pages = 0
    for job_id in job_ids:
        if fetched >= _MAX_DETAILS:
            break
        page_url = f"https://{host}/careersection/{portal}/jobdetail.ftl?job={job_id}&lang=en"
        html = _request(page_url, accept="text/html").decode("utf-8", errors="replace")
        fetched += 1
        if job_id not in html:
            continue
        matched_pages += 1
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        title = _text(title_match.group(1) if title_match else "")
        if title.lower().startswith("careers at"):
            continue
        location_match = re.search(r"(?:primary location|location)\s*[:|-]\s*([^<\n]{3,80})", html, re.I)
        location = location_match.group(1).strip() if location_match else ""
        description = _text(html)
        record = _record(
            f"taleo-{host}-{job_id}", "ats:taleo", title, host.split(".")[0],
            location, page_url, description[:8000], "remote" in location.lower(),
        )
        saw_india = _remember(title, location, record["is_remote"], record, jobs, saw_india)
    if job_ids and matched_pages == 0:
        raise RuntimeError(f"Taleo portal {slug} did not return posting pages")
    return jobs, saw_india


def fetch_enterprise_board(ats: str, slug: str) -> tuple[list[dict], bool]:
    if ats == "smartrecruiters":
        return _smartrecruiters_jobs(slug)
    if ats == "workday":
        return _workday_jobs(slug)
    if ats == "oracle":
        return _oracle_jobs(slug)
    if ats == "sap":
        return _sap_jobs(slug)
    if ats == "taleo":
        return _taleo_jobs(slug)
    raise ValueError(f"Unsupported enterprise ATS: {ats}")


def seed_enterprise_boards_from_jobs() -> int:
    """Register boards already seen on stored listings, then scrape them directly."""
    conn = db.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT job_url, job_url_direct FROM jobs
        WHERE job_url LIKE '%myworkdayjobs.com%' OR job_url_direct LIKE '%myworkdayjobs.com%'
           OR job_url LIKE '%myworkdaysite.com%' OR job_url_direct LIKE '%myworkdaysite.com%'
           OR job_url LIKE '%smartrecruiters.com%' OR job_url_direct LIKE '%smartrecruiters.com%'
           OR job_url LIKE '%oraclecloud.com%' OR job_url_direct LIKE '%oraclecloud.com%'
           OR job_url LIKE '%taleo.net%' OR job_url_direct LIKE '%taleo.net%'
           OR job_url LIKE '%successfactors.%' OR job_url_direct LIKE '%successfactors.%'
           OR job_url LIKE '%sapsf.%' OR job_url_direct LIKE '%sapsf.%'
    """)
    urls = []
    for row in cursor.fetchall():
        urls.append(row["job_url"] or "")
        urls.append(row["job_url_direct"] or "")
    conn.close()
    refs = enterprise_refs_from_urls(urls)
    return db.add_ats_boards(list(refs), source="enterprise_url")
