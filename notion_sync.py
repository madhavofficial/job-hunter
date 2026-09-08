"""Two-way Notion Application Tracker Synchronizer.

Syncs applied software applications between jobs.db and the Notion
"Off-Campus Job Applications Tracker" database.
"""

import os
import re
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import requests
from dotenv import load_dotenv

import db

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID", "3c3ff93a-7912-8151-bccd-c51bc49f0e71")
NOTION_VERSION = "2022-06-28"

VALID_PLATFORMS = {
    "Workday", "Greenhouse", "SmartRecruiters", "LinkedIn",
    "Oracle Cloud", "iCIMS", "Ashby", "Keka", "Direct Portal"
}

VALID_STATUSES = {
    "Applied", "Under Review", "Assessment / OA", "Interview",
    "Account Created", "Rejected", "Assessment Received",
    "Recruiter Reviewing", "In Consideration", "Under Consideration"
}


def get_headers() -> Dict[str, str]:
    token = os.getenv("NOTION_TOKEN")
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json"
    }


def is_notion_configured() -> bool:
    token = os.getenv("NOTION_TOKEN")
    return bool(token and token.startswith("ntn_"))


# Canonical registry mapping known companies to their ATS platform and candidate status portal URL
COMPANY_ATS_REGISTRY: Dict[str, Tuple[str, str]] = {
    # Workday portals
    "hewlett packard enterprise": ("Workday", "https://hpe.wd5.myworkdayjobs.com/en-US/Jobsathpe/userHome"),
    "hpe": ("Workday", "https://hpe.wd5.myworkdayjobs.com/en-US/Jobsathpe/userHome"),
    "hp (hewlett-packard)": ("Workday", "https://hp.wd5.myworkdayjobs.com/en-US/ExternalCareerSite/userHome"),
    "hp": ("Workday", "https://hp.wd5.myworkdayjobs.com/en-US/ExternalCareerSite/userHome"),
    "adobe": ("Workday", "https://adobe.wd5.myworkdayjobs.com/en-US/external_experienced/userHome"),
    "citi": ("Workday", "https://citi.wd5.myworkdayjobs.com/en-US/2/userHome"),
    "philips": ("Workday", "https://philips.wd3.myworkdayjobs.com/en-US/jobs-and-careers/userHome"),
    "pwc": ("Workday", "https://pwc.wd3.myworkdayjobs.com/en-US/Global_Experienced_Careers/userHome"),
    "fedex": ("Workday", "https://fedex.wd1.myworkdayjobs.com/en-US/FXE-MEISA-External/userHome"),
    "hitachi": ("Workday", "https://hitachi.wd1.myworkdayjobs.com/en-US/hitachi/userHome"),
    "thermo fisher": ("Workday", "https://thermofisher.wd5.myworkdayjobs.com/en-US/ThermoFisherCareers/userHome"),
    "salesforce": ("Workday", "https://salesforce.wd12.myworkdayjobs.com/en-US/External_Career_Site/userHome"),
    "nike": ("Workday", "https://nike.wd1.myworkdayjobs.com/en-US/nke/userHome"),
    "motorola": ("Workday", "https://motorolasolutions.wd5.myworkdayjobs.com/en-US/Careers/userHome"),
    "ebay": ("Workday", "https://ebay.wd5.myworkdayjobs.com/en-US/apply/userHome"),
    "zoom": ("Workday", "https://zoom.wd5.myworkdayjobs.com/en-US/Zoom/userHome"),
    "fidelity": ("Workday", "https://wd1.myworkdaysite.com/recruiting/fmr/FidelityCareers/userHome"),
    "solventum": ("Workday", "https://healthcare.wd1.myworkdayjobs.com/en-US/Search/userHome"),
    "natwest": ("Workday", "https://rbs.wd3.myworkdayjobs.com/en-US/RBS/userHome"),
    "rbs": ("Workday", "https://rbs.wd3.myworkdayjobs.com/en-US/RBS/userHome"),
    "ecolab": ("Workday", "https://ecolab.wd1.myworkdayjobs.com/en-US/Ecolab_External/userHome"),
    "fujitsu": ("Workday", "https://fujitsu.wd3.myworkdayjobs.com/en-US/Fujitsu/userHome"),
    "universal robots": ("Workday", "https://teradyne.wd1.myworkdayjobs.com/en-US/Teradyne/userHome"),
    "greif": ("Workday", "https://greif.wd5.myworkdayjobs.com/en-US/Greif_Careers/userHome"),
    "experity": ("Workday", "https://experityhealth.wd5.myworkdayjobs.com/en-US/ExperityCareers/userHome"),

    # Oracle Cloud & Taleo
    "jpmorgan": ("Oracle Cloud", "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/my-profile"),
    "jpmc": ("Oracle Cloud", "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/my-profile"),
    "goldman": ("Oracle Cloud", "https://hdpc.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/LateralHiring/my-profile"),
    "oracle": ("Oracle Cloud", "https://eeho.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/jobsearch/my-profile"),
    "honeywell": ("Oracle Cloud", "https://ibqbjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/Honeywell/my-profile"),
    "kroll": ("Oracle Cloud", "https://hcxs.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/my-profile"),
    "pearson": ("Oracle Cloud", "https://hccz.fa.em3.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_2/my-profile"),
    "unitedhealth": ("Oracle Cloud", "https://uhg.taleo.net/careersection/10780/mysubmissions.ftl"),
    "uhg": ("Oracle Cloud", "https://uhg.taleo.net/careersection/10780/mysubmissions.ftl"),

    # Greenhouse
    "stripe": ("Greenhouse", "https://boards.greenhouse.io/stripe"),
    "solarwinds": ("Greenhouse", "https://boards.greenhouse.io/solarwinds"),
    "tracelink": ("Greenhouse", "https://job-boards.greenhouse.io/tracelinkinc"),
    "digitalocean": ("Greenhouse", "https://boards.greenhouse.io/digitalocean"),

    # Ashby
    "wisdom": ("Ashby", "https://jobs.ashbyhq.com/Wisdom-AI"),

    # iCIMS
    "blackhawk": ("iCIMS", "https://apac-blackhawknetwork.icims.com/jobs/dashboard"),

    # SmartRecruiters
    "ixigo": ("SmartRecruiters", "https://my.smartrecruiters.com/identity/public/sign-in"),
    "linkedin": ("SmartRecruiters", "https://my.smartrecruiters.com/identity/public/sign-in"),

    # Keka
    "impact analytics": ("Keka", "https://impactanalytics.keka.com/careers/"),

    # Enterprise Direct Portals & SuccessFactors
    "qualcomm": ("Direct Portal", "https://careers.qualcomm.com/careers/userHome"),
    "siemens": ("Direct Portal", "https://jobs.siemens.com/careers/userHome"),
    "ibm": ("Direct Portal", "https://careers.ibm.com/en_US/careers/YourApplications"),
    "amazon": ("Direct Portal", "https://www.amazon.jobs/applicant"),
    "cisco": ("Direct Portal", "https://careers.cisco.com/global/en/candidatehub"),
    "dhl": ("Direct Portal", "https://careers.dhl.com/global/en/candidatehub"),
    "microsoft": ("Direct Portal", "https://apply.careers.microsoft.com/applicant"),
    "bt group": ("Direct Portal", "https://career2.successfactors.eu/portalcareer?company=britisht01P1"),
    "moody": ("Direct Portal", "https://career8.successfactors.com/career?company=MoodysProd"),
    "sap": ("Direct Portal", "https://career012.successfactors.eu/career?company=SAP"),
    "tata consultancy": ("Direct Portal", "https://ibegin.tcs.com/iBegin/"),
    "tcs": ("Direct Portal", "https://ibegin.tcs.com/iBegin/"),
    "infosys": ("Direct Portal", "https://career.infosys.com/"),
    "xerox": ("Direct Portal", "https://xerox.avature.net/"),
    "united airlines": ("Direct Portal", "https://careers.united.com/"),
    "corning": ("Direct Portal", "https://corningjobs.corning.com/"),
    "ge vernova": ("Direct Portal", "https://jobs.gevernova.com/global/en/candidatehub"),
    "msd": ("Direct Portal", "https://jobs.msd.com/gb/en/candidatehub"),
    "deloitte": ("Direct Portal", "https://apply.deloitte.com/careers"),
    "cgi": ("Direct Portal", "https://cgi.njoyn.com/"),
    "ust": ("Direct Portal", "https://usource.ripplehire.com/candidate/"),
    "harman": ("Direct Portal", "https://jobsearch.harman.com/en_US/careers/Profile#myApplications"),
    "standard chartered": ("Direct Portal", "https://www.sc.com/en/careers/experienced-professionals/"),
    "litmus7": ("Direct Portal", "https://litmus7.com/careers"),
    "42 learn": ("Direct Portal", "https://42learn.com"),
    "polestar analytics": ("Direct Portal", "https://www.polestarllp.com/careers"),
    "pyjamahr": ("Direct Portal", "https://app.pyjamahr.com/"),
    "bharattech": ("Direct Portal", "https://bharattech.in/careers"),
    "sentlogic": ("Direct Portal", "https://sentlogic.com/careers"),
    "stitch": ("Direct Portal", "https://stitch.money/careers"),
    "shopos": ("Direct Portal", "https://shopos.ai/careers"),
}


def resolve_company_ats(company: str) -> Optional[Tuple[str, str]]:
    """Resolves company name to (platform, status_portal_url) if known."""
    if not company:
        return None
    co_l = company.lower().strip()
    for k in sorted(COMPANY_ATS_REGISTRY.keys(), key=lambda x: len(x), reverse=True):
        if len(k) <= 3:
            if re.search(r"\b" + re.escape(k) + r"\b", co_l):
                return COMPANY_ATS_REGISTRY[k]
        else:
            if k in co_l:
                return COMPANY_ATS_REGISTRY[k]
    return None


def map_platform(url: str, site: str = "", company: str = "") -> str:
    # 1. Company check takes precedence for known enterprise ATS
    co_res = resolve_company_ats(company)
    if co_res:
        return co_res[0]

    # 2. Heuristics based on URL
    url_l = (url or "").lower()
    site_l = (site or "").lower()
    if "myworkdayjobs.com" in url_l or "myworkdaysite.com" in url_l or "workday" in url_l:
        return "Workday"
    if "greenhouse.io" in url_l or "gh_jid" in url_l:
        return "Greenhouse"
    if "smartrecruiters.com" in url_l:
        return "SmartRecruiters"
    if "oraclecloud.com" in url_l or "taleo.net" in url_l:
        return "Oracle Cloud"
    if "icims.com" in url_l:
        return "iCIMS"
    if "ashbyhq.com" in url_l:
        return "Ashby"
    if "keka.com" in url_l:
        return "Keka"
    if "linkedin.com" in url_l or site_l == "linkedin":
        return "LinkedIn"
    return "Direct Portal"


def derive_status_portal_url(url: str, platform: str = "", company: str = "", job_id: str = "") -> str:
    """Derives the candidate application status tracking portal URL."""
    # 1. Company-based registry takes top priority
    co_res = resolve_company_ats(company)
    if co_res:
        return co_res[1]

    u = (url or "").strip()
    plat_l = (platform or "").lower().strip()

    # 2. Workday
    if "myworkdayjobs.com" in u or "myworkdaysite.com" in u or plat_l == "workday":
        m = re.match(r"(https?://[^/]+\.myworkday(?:jobs|site)\.com(?:/[^/]+)?/[^/]+)", u)
        if m:
            return f"{m.group(1)}/userHome"
        m_base = re.match(r"(https?://[^/]+\.myworkday(?:jobs|site)\.com)", u)
        if m_base:
            return f"{m_base.group(1)}/userHome"

    # 3. Oracle Cloud & Taleo
    if "oraclecloud.com" in u or plat_l == "oracle cloud":
        m = re.match(r"(https?://[^/]+/hcmUI/CandidateExperience/[^/]+/sites/[^/]+)", u)
        if m:
            return f"{m.group(1)}/my-profile"
    if "taleo.net" in u:
        m = re.match(r"(https?://[^/]+/careersection/[^/]+)", u)
        if m:
            return f"{m.group(1)}/mysubmissions.ftl"

    # 4. iCIMS
    if "icims.com" in u or plat_l == "icims":
        m = re.match(r"(https?://[^/]+\.icims\.com)", u)
        if m:
            return f"{m.group(1)}/jobs/dashboard"

    # 5. SmartRecruiters
    if "smartrecruiters.com" in u or plat_l == "smartrecruiters":
        return "https://my.smartrecruiters.com/identity/public/sign-in"

    # 6. Greenhouse
    if "greenhouse.io" in u or plat_l == "greenhouse":
        m = re.match(r"(https?://(?:boards|job-boards)\.greenhouse\.io/[^/]+)", u)
        if m:
            return m.group(1)

    # 7. Ashby
    if "ashbyhq.com" in u or plat_l == "ashby":
        m = re.match(r"(https?://jobs\.ashbyhq\.com/[^/]+)", u)
        if m:
            return m.group(1)

    # 8. LinkedIn: Direct listing link or LinkedIn Job Tracker
    if "linkedin.com" in u or plat_l == "linkedin" or (job_id and job_id.startswith("li-")):
        if "linkedin.com/jobs/view/" in u:
            return u
        elif job_id and job_id.startswith("li-"):
            lid = job_id.replace("li-", "")
            return f"https://www.linkedin.com/jobs/view/{lid}/"
        return "https://www.linkedin.com/jobs/tracker/applied/"

    # 9. Indeed
    if "indeed.com" in u or (job_id and job_id.startswith("in-")):
        if "indeed.com" in u:
            return u
        return "https://myjobs.indeed.com/applied"

    # 10. Fallback: Job URL
    if u.startswith("http://") or u.startswith("https://"):
        return u

    return ""


def fetch_all_notion_applications() -> Tuple[List[dict], int]:
    """Fetches all entries from Notion database and returns (entries, max_sno)."""
    if not is_notion_configured():
        return [], 0

    headers = get_headers()
    database_id = os.getenv("NOTION_DATABASE_ID", NOTION_DATABASE_ID)
    url = f"https://api.notion.com/v1/databases/{database_id}/query"

    entries = []
    has_more = True
    start_cursor = None
    max_sno = 0

    while has_more:
        payload = {"page_size": 100}
        if start_cursor:
            payload["start_cursor"] = start_cursor

        res = requests.post(url, headers=headers, json=payload, timeout=20)
        if res.status_code != 200:
            print(f"Warning: Notion query failed with code {res.status_code}: {res.text}", file=sys.stderr)
            break

        data = res.json()
        results = data.get("results", [])
        entries.extend(results)

        for p in results:
            sno_val = p.get("properties", {}).get("S.No", {}).get("number")
            if sno_val and isinstance(sno_val, (int, float)) and sno_val > max_sno:
                max_sno = int(sno_val)

        has_more = data.get("has_more", False)
        start_cursor = data.get("next_cursor")

    return entries, max_sno


def push_job_to_notion(job: dict, sno: int) -> Optional[str]:
    """Pushes a single applied job from jobs.db to the Notion Application Tracker."""
    if not is_notion_configured():
        return None

    headers = get_headers()
    database_id = os.getenv("NOTION_DATABASE_ID", NOTION_DATABASE_ID)
    create_url = "https://api.notion.com/v1/pages"

    company = (job.get("company") or "Unknown Company").strip()
    title = (job.get("title") or "Software Engineer").strip()
    job_url = (job.get("job_url_direct") or job.get("job_url") or "").strip()
    job_id = (job.get("job_id") or "").strip()
    site = (job.get("site") or "").strip()

    # Determine date applied
    today_str = datetime.now().strftime("%Y-%m-%d")
    date_val = today_str
    created_at = job.get("created_at") or ""
    if created_at and len(created_at) >= 10:
        date_candidate = created_at[:10]
        if re.match(r"^\d{4}-\d{2}-\d{2}$", date_candidate):
            date_val = date_candidate

    platform = map_platform(job_url, site, company)
    status_portal_url = derive_status_portal_url(job_url, platform, company, job_id)

    properties = {
        "Company": {
            "title": [{"text": {"content": company[:100]}}]
        },
        "Role": {
            "rich_text": [{"text": {"content": title[:100]}}]
        },
        "Status": {
            "select": {"name": "Applied"}
        },
        "Platform / ATS": {
            "select": {"name": platform}
        },
        "S.No": {
            "number": sno
        },
        "Date Applied": {
            "date": {"start": date_val}
        }
    }

    if job_url.startswith("http://") or job_url.startswith("https://"):
        properties["Job Listing Link"] = {"url": job_url}

    if status_portal_url:
        properties["Check Status Portal URL"] = {"url": status_portal_url}

    if job_id:
        properties["Req ID / Job ID"] = {
            "rich_text": [{"text": {"content": job_id[:100]}}]
        }

    body = {
        "parent": {"database_id": database_id},
        "properties": properties
    }

    try:
        res = requests.post(create_url, headers=headers, json=body, timeout=20)
        if res.status_code in (200, 201):
            created_page = res.json()
            return created_page.get("id")
        else:
            print(f"Warning: Failed to create Notion entry for {company}: {res.status_code} {res.text}", file=sys.stderr)
            return None
    except Exception as e:
        print(f"Warning: Exception while pushing {company} to Notion: {e}", file=sys.stderr)
        return None


def sync_applied_to_notion(target_job_id: str = None) -> int:
    """Syncs applied jobs from jobs.db to Notion tracker.
    
    If target_job_id is provided, syncs that specific job.
    If None, scans all applied jobs and adds missing ones.
    """
    if not is_notion_configured():
        return 0

    print(f"\n====================================================")
    print(f"🔄 SYNCHRONIZING APPLICATIONS WITH NOTION TRACKER")
    print(f"====================================================")

    existing_entries, max_sno = fetch_all_notion_applications()
    print(f"-> Found {len(existing_entries)} existing applications in Notion (Highest S.No: {max_sno}).")

    notion_urls = set()
    notion_req_ids = set()
    notion_companies = set()

    for p in existing_entries:
        props = p.get("properties", {})
        u = props.get("Job Listing Link", {}).get("url")
        if u:
            notion_urls.add(u.strip())
        
        req_arr = props.get("Req ID / Job ID", {}).get("rich_text", [])
        if req_arr:
            req_id_str = req_arr[0].get("plain_text", "").strip()
            if req_id_str:
                notion_req_ids.add(req_id_str)

        co_arr = props.get("Company", {}).get("title", [])
        if co_arr:
            co_str = co_arr[0].get("plain_text", "").strip().lower()
            if co_str:
                notion_companies.add(co_str)

    conn = db.get_db_connection()
    cursor = conn.cursor()

    if target_job_id:
        cursor.execute("""
            SELECT job_id, company, title, date_posted, job_url, job_url_direct, site, created_at
            FROM jobs
            WHERE job_id = ? AND status = 'applied'
        """, (target_job_id,))
        jobs_to_sync = [dict(r) for r in cursor.fetchall()]
    else:
        cursor.execute("""
            SELECT job_id, company, title, date_posted, job_url, job_url_direct, site, created_at
            FROM jobs
            WHERE status = 'applied'
            ORDER BY created_at ASC
        """)
        jobs_to_sync = [dict(r) for r in cursor.fetchall()]

    conn.close()

    synced_count = 0
    current_sno = max_sno

    for j in jobs_to_sync:
        u1 = (j.get("job_url") or "").strip()
        u2 = (j.get("job_url_direct") or "").strip()
        jid = (j.get("job_id") or "").strip()
        co_lower = (j.get("company") or "").strip().lower()

        # Check if already present in Notion
        already_in_notion = False
        if jid and jid in notion_req_ids:
            already_in_notion = True
        elif u1 and u1 in notion_urls:
            already_in_notion = True
        elif u2 and u2 in notion_urls:
            already_in_notion = True

        if already_in_notion:
            continue

        current_sno += 1
        page_id = push_job_to_notion(j, current_sno)
        if page_id:
            print(f"✓ [S.No {current_sno}] Added to Notion: {j['company']} — {j['title']} ({j['job_id']})")
            synced_count += 1
            if u1: notion_urls.add(u1)
            if u2: notion_urls.add(u2)
            if jid: notion_req_ids.add(jid)
            time.sleep(0.35)  # Notion rate-limit etiquette

    print(f"-> Notion sync complete: {synced_count} new applications created in tracker.")

    # Also backfill any existing entries missing Check Status Portal URL
    if not target_job_id:
        backfill_missing_status_portal_urls()

    return synced_count


def backfill_missing_status_portal_urls(audit_all: bool = True) -> int:
    """Audits and updates Notion pages where 'Check Status Portal URL' is missing,
    points to a generic job listing (e.g. LinkedIn or Indeed applied), or has a mismatched platform."""
    if not is_notion_configured():
        return 0

    print("\n====================================================")
    print("🔧 AUDITING & UPDATING ATS PLATFORMS & PORTAL URLS")
    print("====================================================")

    entries, _ = fetch_all_notion_applications()
    headers = get_headers()
    updated_count = 0

    for p in entries:
        props = p.get("properties", {})
        existing_portal = (props.get("Check Status Portal URL", {}).get("url") or "").strip()
        existing_plat = props.get("Platform / ATS", {}).get("select", {}).get("name") or ""
        page_id = p.get("id")
        listing_url = (props.get("Job Listing Link", {}).get("url") or "").strip()
        co_arr = props.get("Company", {}).get("title", [])
        co = co_arr[0].get("plain_text", "").strip() if co_arr else ""
        req_arr = props.get("Req ID / Job ID", {}).get("rich_text", [])
        jid = req_arr[0].get("plain_text", "").strip() if req_arr else ""
        sno = props.get("S.No", {}).get("number", 0) or 0

        target_plat = map_platform(listing_url, "", co)
        target_portal = derive_status_portal_url(listing_url, target_plat, co, jid)

        if not target_portal:
            continue

        # If sno <= 57 and portal is already an established ATS (not linkedin/indeed listing), preserve it
        if sno <= 57 and existing_portal and "linkedin.com" not in existing_portal and "indeed.com" not in existing_portal:
            continue

        needs_portal_update = not existing_portal or (existing_portal != target_portal)
        needs_plat_update = target_plat and (target_plat != existing_plat)

        if not needs_portal_update and not needs_plat_update:
            continue

        patch_props = {}
        if needs_portal_update:
            patch_props["Check Status Portal URL"] = {"url": target_portal}
        if needs_plat_update:
            patch_props["Platform / ATS"] = {"select": {"name": target_plat}}

        try:
            res = requests.patch(
                f"https://api.notion.com/v1/pages/{page_id}",
                headers=headers,
                json={"properties": patch_props},
                timeout=15
            )
            if res.status_code == 200:
                details = []
                if needs_plat_update:
                    details.append(f"Platform: {existing_plat} -> {target_plat}")
                if needs_portal_update:
                    details.append(f"Portal: {target_portal}")
                print(f"✓ [S.No {sno}] Updated {co} -> {', '.join(details)}")
                updated_count += 1
                time.sleep(0.35)
            else:
                print(f"Warning: Failed to update page {page_id}: {res.status_code} {res.text}", file=sys.stderr)
        except Exception as e:
            print(f"Warning: Exception updating page {page_id}: {e}", file=sys.stderr)

    print(f"-> Audit and update complete: {updated_count} Notion pages updated with genuine ATS tracking portals.")
    return updated_count


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("--backfill", "--update-portals"):
        backfill_missing_status_portal_urls()
    elif len(sys.argv) > 1 and sys.argv[1]:
        sync_applied_to_notion(sys.argv[1])
    else:
        sync_applied_to_notion()

