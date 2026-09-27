import unittest

from ats_collector import CAREER_BOARD_DOMAINS, discover_board_refs, html_to_text


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
        self.assertIn("monster.com", CAREER_BOARD_DOMAINS)

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


if __name__ == "__main__":
    unittest.main()

