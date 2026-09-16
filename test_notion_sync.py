import unittest
from notion_sync import map_platform, is_notion_configured, derive_status_portal_url


class NotionSyncTests(unittest.TestCase):
    def test_platform_mapping(self):
        self.assertEqual(map_platform("https://adobe.myworkdayjobs.com/en-US/external_experienced/job/123"), "Workday")
        self.assertEqual(map_platform("https://boards.greenhouse.io/stripe/jobs/123"), "Greenhouse")
        self.assertEqual(map_platform("https://jobs.smartrecruiters.com/Acme/456"), "SmartRecruiters")
        self.assertEqual(map_platform("https://www.linkedin.com/jobs/view/4459407986/"), "LinkedIn")
        self.assertEqual(map_platform("", site="linkedin"), "LinkedIn")
        self.assertEqual(map_platform("https://jpmc.fa.oraclecloud.com/hcmUI/job/789"), "Oracle Cloud")
        self.assertEqual(map_platform("https://careers.example.com/job"), "Direct Portal")
        # Company takes precedence even if listing was on LinkedIn
        self.assertEqual(map_platform("https://www.linkedin.com/jobs/view/4464322180/", company="HP"), "Workday")
        self.assertEqual(map_platform("https://www.linkedin.com/jobs/view/4461064345", company="JPMorganChase"), "Oracle Cloud")
        self.assertEqual(map_platform("https://www.linkedin.com/jobs/view/4454538326", company="Stripe"), "Greenhouse")

    def test_derive_status_portal_url(self):
        # Workday
        wd_url = "https://adobe.myworkdayjobs.com/en-US/external_experienced/job/123"
        self.assertEqual(
            derive_status_portal_url(wd_url, "Workday", "Adobe"),
            "https://adobe.wd5.myworkdayjobs.com/en-US/external_experienced/userHome"
        )

        # Oracle Cloud
        oracle_url = "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/requisitions/preview/210"
        self.assertEqual(
            derive_status_portal_url(oracle_url, "Oracle Cloud", "JPMC"),
            "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/my-profile"
        )

        # Taleo
        taleo_url = "https://oracle.taleo.net/careersection/2/jobdetail.ftl?job=123"
        self.assertEqual(
            derive_status_portal_url(taleo_url, "Taleo", "Oracle"),
            "https://eeho.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/jobsearch/my-profile"
        )

        # Greenhouse
        gh_url = "https://boards.greenhouse.io/stripe/jobs/123"
        self.assertEqual(
            derive_status_portal_url(gh_url, "Greenhouse", "Stripe"),
            "https://boards.greenhouse.io/stripe"
        )

        # Ashby
        ashby_url = "https://jobs.ashbyhq.com/posthog/123"
        self.assertEqual(
            derive_status_portal_url(ashby_url, "Ashby", "PostHog"),
            "https://jobs.ashbyhq.com/posthog"
        )

        # SmartRecruiters
        sr_url = "https://jobs.smartrecruiters.com/Acme/456"
        self.assertEqual(
            derive_status_portal_url(sr_url, "SmartRecruiters", "Acme"),
            "https://my.smartrecruiters.com/identity/public/sign-in"
        )

        # Known Enterprise Portals by company resolution
        self.assertEqual(
            derive_status_portal_url("https://www.linkedin.com/jobs/view/4464322180/", "LinkedIn", "HP"),
            "https://hp.wd5.myworkdayjobs.com/en-US/ExternalCareerSite/userHome"
        )
        self.assertEqual(
            derive_status_portal_url("https://www.linkedin.com/jobs/view/4461064345", "LinkedIn", "JPMorganChase"),
            "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/my-profile"
        )
        self.assertEqual(
            derive_status_portal_url("https://careers.qualcomm.com/jobs/123", "Direct Portal", "Qualcomm"),
            "https://careers.qualcomm.com/careers/userHome"
        )

        # Fallback for companies without a dedicated enterprise ATS
        startup_url = "https://www.linkedin.com/jobs/view/4454204205"
        self.assertEqual(
            derive_status_portal_url(startup_url, "LinkedIn", "JuiceLabs AI"),
            "https://www.linkedin.com/jobs/view/4454204205"
        )

    def test_notion_configured(self):
        # When token is present in .env, is_notion_configured returns True
        self.assertTrue(is_notion_configured())

    def test_normalize_job_url(self):
        from notion_sync import normalize_job_url
        self.assertEqual(normalize_job_url("https://www.linkedin.com/jobs/view/12345/?refId=abc&tracking=1"), "https://linkedin.com/jobs/view/12345")
        self.assertEqual(normalize_job_url("http://example.com/careers/job/"), "https://example.com/careers/job")
        self.assertEqual(normalize_job_url("https://hpe.wd5.myworkdayjobs.com/Jobs/123"), "https://hpe.wd5.myworkdayjobs.com/jobs/123")
        self.assertEqual(normalize_job_url(""), "")

    def test_extract_linkedin_id(self):
        from notion_sync import extract_linkedin_id
        self.assertEqual(extract_linkedin_id("https://www.linkedin.com/jobs/view/4459407986/"), "li-4459407986")
        self.assertEqual(extract_linkedin_id("https://linkedin.com/jobs/view/123456789?refId=xyz"), "li-123456789")
        self.assertIsNone(extract_linkedin_id("https://boards.greenhouse.io/stripe/jobs/123"))

    def test_push_job_to_notion_filters_dummy_and_test_jobs(self):
        from notion_sync import push_job_to_notion
        # Dummy records should be rejected before any API call
        self.assertIsNone(push_job_to_notion({"company": "Not Found", "title": "Not Found"}, 1))
        self.assertIsNone(push_job_to_notion({"company": "TestCo", "title": "Backend Engineer"}, 1))
        self.assertIsNone(push_job_to_notion({"job_id": "test_123", "company": "Google", "title": "SWE"}, 1))

    def test_sync_notion_to_db_inbound(self):
        import db
        from notion_sync import sync_notion_to_db

        mock_entries = [
            {
                "id": "mock-page-id-123",
                "properties": {
                    "Company": {"title": [{"plain_text": "Mock Enterprise Inc"}]},
                    "Role": {"rich_text": [{"plain_text": "AI Engineer"}]},
                    "Job Listing Link": {"url": "https://careers.example.com/mock-123"},
                    "Date Applied": {"date": {"start": "2026-09-15"}},
                    "Status": {"select": {"name": "Applied"}},
                    "S.No": {"number": 999},
                    "Req ID / Job ID": {"rich_text": [{"plain_text": "mock-req-123"}]},
                }
            },
            {
                "id": "mock-page-id-456",
                "properties": {
                    "Company": {"title": [{"plain_text": "Mock Rejected Corp"}]},
                    "Role": {"rich_text": [{"plain_text": "Data Scientist"}]},
                    "Job Listing Link": {"url": "https://careers.example.com/mock-456"},
                    "Date Applied": {"date": {"start": "2026-09-14"}},
                    "Status": {"select": {"name": "Rejected"}},
                    "S.No": {"number": 998},
                    "Req ID / Job ID": {"rich_text": [{"plain_text": "mock-req-456"}]},
                }
            }
        ]

        conn = db.get_db_connection()
        conn.execute("DELETE FROM jobs WHERE job_id IN ('mock-req-123', 'mock-req-456')")
        conn.commit()
        conn.close()

        try:
            updated, inserted = sync_notion_to_db(entries=mock_entries)
            self.assertEqual(inserted, 2)

            conn = db.get_db_connection()
            r1 = conn.execute("SELECT * FROM jobs WHERE job_id = 'mock-req-123'").fetchone()
            self.assertIsNotNone(r1)
            self.assertEqual(r1["status"], "applied")
            self.assertEqual(r1["company"], "Mock Enterprise Inc")

            r2 = conn.execute("SELECT * FROM jobs WHERE job_id = 'mock-req-456'").fetchone()
            self.assertIsNotNone(r2)
            self.assertEqual(r2["status"], "rejected")
            conn.close()

            # Now test update behavior: change status of mock-123 to Rejected
            mock_entries[0]["properties"]["Status"]["select"]["name"] = "Rejected"
            updated2, inserted2 = sync_notion_to_db(entries=mock_entries)
            self.assertEqual(updated2, 1)
            self.assertEqual(inserted2, 0)

            conn = db.get_db_connection()
            r1_updated = conn.execute("SELECT status FROM jobs WHERE job_id = 'mock-req-123'").fetchone()
            self.assertEqual(r1_updated["status"], "rejected")
            conn.close()
        finally:
            conn = db.get_db_connection()
            conn.execute("DELETE FROM jobs WHERE job_id IN ('mock-req-123', 'mock-req-456')")
            conn.commit()
            conn.close()


if __name__ == "__main__":
    unittest.main()

