import unittest
from notion_sync import map_platform, is_notion_configured


class NotionSyncTests(unittest.TestCase):
    def test_platform_mapping(self):
        self.assertEqual(map_platform("https://adobe.myworkdayjobs.com/en-US/external_experienced/job/123"), "Workday")
        self.assertEqual(map_platform("https://boards.greenhouse.io/stripe/jobs/123"), "Greenhouse")
        self.assertEqual(map_platform("https://jobs.smartrecruiters.com/Acme/456"), "SmartRecruiters")
        self.assertEqual(map_platform("https://www.linkedin.com/jobs/view/4459407986/"), "LinkedIn")
        self.assertEqual(map_platform("", site="linkedin"), "LinkedIn")
        self.assertEqual(map_platform("https://jpmc.fa.oraclecloud.com/hcmUI/job/789"), "Oracle Cloud")
        self.assertEqual(map_platform("https://careers.example.com/job"), "Direct Portal")

    def test_notion_configured(self):
        # When token is present in .env, is_notion_configured returns True
        self.assertTrue(is_notion_configured())


if __name__ == "__main__":
    unittest.main()
