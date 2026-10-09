import os
import tempfile
import unittest
from unittest.mock import patch

import db
from ats_collector import (
    CAREER_BOARD_DOMAINS,
    INDIA_DISCOVERY_LOCATIONS,
    _ashby_location,
    _is_india_or_remote,
    _lever_location,
    board_persist_fields,
    company_name_from_listing,
    discover_board_refs,
    html_to_text,
    is_target_engineering_title,
)


class ATSCollectorTests(unittest.TestCase):
    def test_discovers_supported_boards_without_company_config(self):
        refs = discover_board_refs([
            "https://jobs.ashbyhq.com/openai/123",
            "https://boards.greenhouse.io/anthropic/jobs/456",
            "https://jobs.lever.co/shopback-2/789",
            "https://example.com/jobs/1",
        ])
        self.assertEqual(refs, {("ashby", "openai"), ("greenhouse", "anthropic"), ("lever", "shopback-2")})

    def test_strips_html_descriptions(self):
        self.assertEqual(html_to_text("<p>Python &amp; FastAPI</p><ul><li>Backend</li></ul>"), "Python & FastAPI Backend")

    def test_career_discovery_is_provider_based_not_company_configured(self):
        self.assertIn("myworkdayjobs.com", CAREER_BOARD_DOMAINS)
        self.assertIn("oraclecloud.com", CAREER_BOARD_DOMAINS)
        self.assertNotIn("monster.com", CAREER_BOARD_DOMAINS)

    def test_search_registers_enterprise_tenants_without_storing_jobs(self):
        from ats_collector import discover_enterprise_boards
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "jobs.db")
            with patch.object(db, "DB_PATH", path), patch(
                "ats_collector.search_urls",
                return_value=[
                    "https://qualys.wd5.myworkdayjobs.com/en-US/Careers/job/Pune/Engineer_R1",
                    "https://jobs.jobvite.com/example/job/abc",
                ],
            ):
                db.init_db()
                added = discover_enterprise_boards()
                conn = db.get_db_connection()
                boards = conn.execute("SELECT ats, board_slug, source FROM ats_boards").fetchall()
                jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
                conn.close()
        self.assertEqual(added, 1)
        self.assertEqual(jobs, 0)
        self.assertEqual(
            [(row["ats"], row["board_slug"], row["source"]) for row in boards],
            [("workday", "qualys.wd5.myworkdayjobs.com/careers", "search_dork")],
        )
        self.assertNotIn("India OR remote", INDIA_DISCOVERY_LOCATIONS)
        self.assertIn("India", INDIA_DISCOVERY_LOCATIONS)

    def test_career_listing_handles_dict_address_country(self):
        from unittest.mock import patch, MagicMock
        from ats_collector import _career_listing_from_url
        import json

        html_sample = """
        <html>
        <head><title>Test Job</title></head>
        <body>
        <script type="application/ld+json">
        {
            "@type": "JobPosting",
            "title": "Software Engineer Intern",
            "hiringOrganization": {"name": "Acme Corp"},
            "jobLocation": {
                "address": {
                    "addressLocality": "Bengaluru",
                    "addressRegion": "Karnataka",
                    "addressCountry": {"@type": "Country", "name": "India"}
                }
            },
            "description": "<p>Great opportunity</p>"
        }
        </script>
        </body>
        </html>
        """
        mock_resp = MagicMock()
        mock_resp.read.return_value = html_sample.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("ats_collector.urlopen", return_value=mock_resp):
            listing = _career_listing_from_url("https://careers.acme.com/jobs/123", "acme.com")

        self.assertIsNotNone(listing)
        self.assertEqual(listing["title"], "Software Engineer Intern")
        self.assertEqual(listing["company"], "Acme Corp")
        self.assertEqual(listing["location"], "Bengaluru, Karnataka, India")

    def test_career_listing_rejects_non_india_location(self):
        from unittest.mock import MagicMock
        from ats_collector import _career_listing_from_url

        html_sample = """
        <html><head><title>Test Job</title></head><body>
        <script type="application/ld+json">
        {
            "@type": "JobPosting",
            "title": "Software Engineer",
            "hiringOrganization": {"name": "Acme Corp"},
            "jobLocation": {"address": {"addressLocality": "San Francisco", "addressCountry": "United States"}},
            "description": "<p>Build backend services</p>"
        }
        </script></body></html>
        """
        mock_resp = MagicMock()
        mock_resp.read.return_value = html_sample.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        with patch("ats_collector.urlopen", return_value=mock_resp):
            listing = _career_listing_from_url("https://careers.acme.com/jobs/999", "acme.com")
        self.assertIsNone(listing)

    def test_curated_ats_boards_present(self):
        from ats_collector import CURATED_ATS_BOARDS
        self.assertIn(("greenhouse", "anthropic"), CURATED_ATS_BOARDS)
        self.assertIn(("ashby", "perplexity"), CURATED_ATS_BOARDS)

    def test_is_india_or_remote(self):
        from ats_collector import _is_india_or_remote
        self.assertTrue(_is_india_or_remote("Bengaluru, India", False))
        self.assertTrue(_is_india_or_remote("Ahmedabad, Gujarat", False))
        self.assertTrue(_is_india_or_remote("Kochi, Kerala", False))
        self.assertTrue(_is_india_or_remote("Remote, Global", True))
        self.assertTrue(_is_india_or_remote("Remote, Worldwide", True))
        self.assertTrue(_is_india_or_remote("Remote (India)", True))
        self.assertFalse(_is_india_or_remote("San Francisco; New York City", True))
        self.assertFalse(_is_india_or_remote("Belgrade; London; Berlin", True))
        self.assertFalse(_is_india_or_remote("Customer Solution Architect (AMER)", True))
        self.assertFalse(_is_india_or_remote("Support Engineer (EMEA)", True))
        self.assertFalse(_is_india_or_remote("Remote US", True))
        self.assertFalse(_is_india_or_remote("US - REMOTE", True))
        self.assertFalse(_is_india_or_remote("Remote", True))
        self.assertFalse(_is_india_or_remote("", True))
        self.assertFalse(_is_india_or_remote("Dubai; Abu Dhabi", False))
        self.assertFalse(_is_india_or_remote("Vietnam", False))
        self.assertFalse(_is_india_or_remote("Dublin, Ireland", False))
        self.assertTrue(_is_india_or_remote("Worldwide", True))
        self.assertTrue(_is_india_or_remote("IN", False))
        self.assertTrue(_is_india_or_remote("Remote; IN", True))
        self.assertTrue(_is_india_or_remote("Noida; IN", False))
        self.assertFalse(_is_india_or_remote("Remote, Global - US hours", True))
        self.assertFalse(_is_india_or_remote("Brownsburg, IN; US", False))
        self.assertFalse(_is_india_or_remote("Carmel, IN; US", False))
        self.assertFalse(_is_india_or_remote("USA - Indianapolis, IN; Indiana", False))
        self.assertFalse(_is_india_or_remote("Indianapolis, IN", False))
        self.assertFalse(_is_india_or_remote("Remote - International", True))
        self.assertFalse(is_target_engineering_title("Don't see a fit? Fill out a general application!"))

    def test_lever_country_is_part_of_the_location_gate(self):
        location = _lever_location({
            "categories": {"location": "Florida", "allLocations": ["Florida"]},
            "country": "US",
            "workplaceType": "remote",
        })
        self.assertEqual(location, "Florida; US")
        self.assertFalse(_is_india_or_remote(location, True))

    def test_ashby_address_country_rejects_us_remote_label(self):
        location = _ashby_location({
            "location": "San Francisco",
            "isRemote": None,
            "address": {"postalAddress": {
                "addressLocality": "San Francisco",
                "addressRegion": "California",
                "addressCountry": "United States",
            }},
        })
        self.assertIn("United States", location)
        self.assertFalse(_is_india_or_remote(location, False))

    def test_company_name_prefers_ats_payload(self):
        self.assertEqual(company_name_from_listing({"company_name": "GitLab"}, "gitlab"), "GitLab")
        self.assertEqual(company_name_from_listing({}, "bjak-career"), "Bjak Career")

    def test_enterprise_daily_limit_cycles_catalog_in_a_week(self):
        from ats_collector import enterprise_daily_limit
        self.assertEqual(enterprise_daily_limit(0), 0)
        self.assertEqual(enterprise_daily_limit(4), 8)
        self.assertEqual(enterprise_daily_limit(305), 44)
        self.assertEqual(enterprise_daily_limit(1744), 250)
        self.assertEqual(enterprise_daily_limit(5000), 300)

    def test_board_persist_fields(self):
        self.assertEqual(board_persist_fields("ok", 4, True), (4, 1))
        self.assertEqual(board_persist_fields("ok", 0, True), (0, 1))
        self.assertEqual(board_persist_fields("ok", 0, False), (0, 0))
        self.assertEqual(board_persist_fields("ok", 0, False, "greenhouse"), (0, 0))
        self.assertEqual(board_persist_fields("ok", 0, False, "sap"), (0, 1))
        self.assertEqual(board_persist_fields("ok", 0, False, "taleo"), (0, 1))
        self.assertEqual(board_persist_fields("ok", 0, False, "workday"), (0, 1))
        self.assertEqual(board_persist_fields("gone", 0, False, "taleo"), (None, 0))
        self.assertEqual(board_persist_fields("error", 0, False), (None, None))

    def test_unscraped_boards_are_scraped_before_recent_boards(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "boards.db")
            with patch.object(db, "DB_PATH", path):
                db.add_ats_boards([("ashby", "oldco"), ("ashby", "newco")], source="test")
                db.update_ats_board_scraped("ashby", "oldco", job_count=3, is_active=1)
                first = db.get_registered_ats_boards(active_only=True, limit=10)
                self.assertEqual(first[0], ("ashby", "newco"))
                db.update_ats_board_scraped("ashby", "oldco", job_count=None, is_active=None)
                conn = db.get_db_connection()
                count = conn.execute(
                    "SELECT job_count FROM ats_boards WHERE board_slug = 'oldco'"
                ).fetchone()[0]
                conn.close()
                self.assertEqual(count, 3)
                db.add_ats_boards([("ashby", "usonly")], source="test")
                db.update_ats_board_scraped("ashby", "usonly", job_count=0, is_active=0)
                active = db.get_registered_ats_boards(active_only=True)
                self.assertNotIn(("ashby", "usonly"), active)
                db.add_ats_boards([("sap", "career8.successfactors.com/moodysprod")], source="test")
                db.update_ats_board_scraped("sap", "career8.successfactors.com/moodysprod", job_count=0, is_active=0)
                restored = db.reactivate_enterprise_boards(("sap", "taleo", "workday", "oracle", "smartrecruiters"))
                self.assertEqual(restored, 1)
                active = db.get_registered_ats_boards(active_only=True, ats="sap")
                self.assertIn(("sap", "career8.successfactors.com/moodysprod"), active)
                db.add_ats_boards([("sap", "career8.successfactors.com/moodysprod")], source="test")
                db.update_ats_board_scraped("sap", "career8.successfactors.com/moodysprod", job_count=0, is_active=0)
                restored = db.reactivate_enterprise_boards(("sap", "taleo", "workday", "oracle", "smartrecruiters"))
                self.assertEqual(restored, 1)
                active = db.get_registered_ats_boards(active_only=True, ats="sap")
                self.assertIn(("sap", "career8.successfactors.com/moodysprod"), active)


    def test_linkedin_easy_apply_rows_are_matchable(self):
        import pandas as pd
        from collector import linkedin_easy_apply_rows, scrape_listings
        from screening import is_dashboard_listing
        frame = pd.DataFrame([
            {
                "site": "linkedin",
                "title": "Software Engineer",
                "company": "Qualys",
                "location": "Pune, India",
                "job_url": "https://www.linkedin.com/jobs/view/1",
                "job_url_direct": "https://www.linkedin.com/jobs/view/1",
            },
            {
                "site": "indeed",
                "title": "Software Engineer",
                "company": "Qualys",
                "location": "Pune, India",
                "job_url": "https://in.indeed.com/viewjob?jk=1",
                "job_url_direct": "https://in.indeed.com/viewjob?jk=1",
            },
        ])
        kept = linkedin_easy_apply_rows(frame)
        self.assertEqual(list(kept["site"]), ["linkedin_easy_apply"])
        job = kept.iloc[0].to_dict()
        self.assertTrue(is_dashboard_listing(job))
        self.assertFalse(is_dashboard_listing({**job, "site": "linkedin"}))
        self.assertFalse(is_dashboard_listing({**job, "location": "Austin, TX, United States"}))

        with patch("collector.scrape_jobs", return_value=frame) as scrape:
            result = scrape_listings(
                easy_apply=True,
                site_name=["linkedin", "indeed"],
                search_term="Software Engineer",
            )
        self.assertEqual(scrape.call_args.kwargs["site_name"], ["linkedin"])
        self.assertTrue(scrape.call_args.kwargs["easy_apply"])
        self.assertEqual(list(result["site"]), ["linkedin_easy_apply"])

    def test_easy_apply_run_stays_inside_one_linkedin_page_budget(self):
        import pandas as pd
        from collector import EASY_APPLY_PAGE_SIZE, EASY_APPLY_QUERY_BUDGET, easy_apply_queries, run_easy_apply_collector
        day_zero = easy_apply_queries(0)
        day_one = easy_apply_queries(1)
        self.assertLessEqual(len(day_zero), EASY_APPLY_QUERY_BUDGET)
        self.assertLessEqual(EASY_APPLY_QUERY_BUDGET, 8)
        self.assertLessEqual(EASY_APPLY_PAGE_SIZE, 10)
        self.assertNotEqual(day_zero[0], day_one[0])

        with patch("collector.easy_apply_queries", return_value=[("Software Engineer", False), ("AI Engineer", True)]), \
             patch("collector.db.init_db"), \
             patch("collector.db.add_jobs", return_value=1), \
             patch("collector.time.sleep"), \
             patch("collector.scrape_listings", return_value=pd.DataFrame({"site": ["linkedin_easy_apply"]})) as scrape:
            stored = run_easy_apply_collector(20, 168)
        self.assertEqual(stored, 2)
        self.assertEqual(scrape.call_count, 2)
        self.assertEqual(scrape.call_args_list[0].kwargs["results_wanted"], EASY_APPLY_PAGE_SIZE)
        self.assertFalse(scrape.call_args_list[0].kwargs["is_remote"])
        self.assertTrue(scrape.call_args_list[1].kwargs["is_remote"])

    def test_gmail_alerts_are_ingested_and_bulk_linkedin_is_not(self):
        from ingest_email_jobs import jobs_for_ingest, reopen_known_alert_copies
        from screening import is_dashboard_listing
        kept = jobs_for_ingest([
            {
                "job_id": "li-1",
                "site": "linkedin",
                "title": "Software Engineer",
                "company": "Qualys",
                "location": "Pune, India",
                "job_url": "https://www.linkedin.com/jobs/view/1",
                "job_url_direct": "https://www.linkedin.com/jobs/view/1",
            },
            {
                "site": "indeed",
                "title": "Software Engineer",
                "job_url": "https://www.indeed.com/viewjob?jk=abc",
                "job_url_direct": "https://www.indeed.com/viewjob?jk=abc",
            },
            {
                "site": "ats:greenhouse",
                "title": "Software Engineer",
                "company": "SingleStore",
                "location": "Hyderabad, India",
                "job_url": "https://job-boards.greenhouse.io/singlestore/jobs/1",
                "job_url_direct": "https://job-boards.greenhouse.io/singlestore/jobs/1",
            },
        ])
        self.assertEqual([job["site"] for job in kept], ["gmail", "ats:greenhouse"])
        alert = kept[0]
        self.assertTrue(is_dashboard_listing(alert))
        self.assertFalse(is_dashboard_listing(dict(alert, location="San Francisco, CA, United States")))
        scraped = {
            "site": "linkedin",
            "title": "Software Engineer",
            "location": "Bengaluru, India",
            "job_url": "https://www.linkedin.com/jobs/view/9",
            "job_url_direct": "https://www.linkedin.com/jobs/view/9",
        }
        self.assertFalse(is_dashboard_listing(scraped))

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "jobs.db")
            with patch.object(db, "DB_PATH", path):
                db.init_db()
                conn = db.get_db_connection()
                conn.execute(
                    """
                    INSERT INTO jobs (job_id, site, job_url, title, company, location, status, score, matching_notes)
                    VALUES ('li-1', 'linkedin', 'https://www.linkedin.com/jobs/view/1',
                            'Software Engineer', 'Qualys', 'Pune, India', 'rejected', 0,
                            'REJECTED: Listing is not a direct India or worldwide employer posting.')
                    """
                )
                conn.execute(
                    """
                    INSERT INTO jobs (job_id, site, job_url, title, company, location, status, score, matching_notes)
                    VALUES ('li-2', 'linkedin', 'https://www.linkedin.com/jobs/view/2',
                            'Recruiter', 'Qualys', 'Pune, India', 'rejected', 0,
                            'REJECTED: Role title is outside the target software/AI scope.')
                    """
                )
                conn.commit()
                conn.close()
                other = dict(alert, job_id="li-2", job_url="https://www.linkedin.com/jobs/view/2", title="Recruiter")
                self.assertEqual(reopen_known_alert_copies([alert, other]), 1)
                conn = db.get_db_connection()
                first = conn.execute("SELECT site, status FROM jobs WHERE job_id = 'li-1'").fetchone()
                second = conn.execute("SELECT site, status FROM jobs WHERE job_id = 'li-2'").fetchone()
                conn.close()
                self.assertEqual((first["site"], first["status"]), ("gmail", "scraped"))
                self.assertEqual((second["site"], second["status"]), ("gmail", "rejected"))

    def test_is_target_engineering_title(self):
        from ats_collector import is_target_engineering_title
        # Target engineering / technical roles
        self.assertTrue(is_target_engineering_title("Software Engineer"))
        self.assertTrue(is_target_engineering_title("AI Engineer"))
        self.assertTrue(is_target_engineering_title("Backend Developer Intern"))
        self.assertTrue(is_target_engineering_title("Founding Engineer"))
        self.assertTrue(is_target_engineering_title("Associate Data Scientist"))
        self.assertTrue(is_target_engineering_title("Machine Learning Researcher"))

        # Non-technical / business domains rejected early
        self.assertFalse(is_target_engineering_title("Account Executive"))
        self.assertFalse(is_target_engineering_title("Director of Sales"))
        self.assertFalse(is_target_engineering_title("Product Marketing Manager"))
        self.assertFalse(is_target_engineering_title("Legal Counsel"))
        self.assertFalse(is_target_engineering_title("Senior Recruiter"))
        self.assertFalse(is_target_engineering_title("Customer Success Manager"))
        self.assertFalse(is_target_engineering_title("Public Policy Associate"))

        # Senior / leadership levels rejected early
        self.assertFalse(is_target_engineering_title("Senior Software Engineer"))
        self.assertFalse(is_target_engineering_title("Staff Platform Engineer"))
        self.assertFalse(is_target_engineering_title("Principal Backend Engineer"))
        self.assertFalse(is_target_engineering_title("Engineering Director"))
        self.assertFalse(is_target_engineering_title("Team Lead, Android Core Product"))


if __name__ == "__main__":
    unittest.main()


