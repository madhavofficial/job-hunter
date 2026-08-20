import unittest

from ats_collector import discover_board_refs, html_to_text


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


if __name__ == "__main__":
    unittest.main()
