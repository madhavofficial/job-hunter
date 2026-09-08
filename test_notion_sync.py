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


if __name__ == "__main__":
    unittest.main()

