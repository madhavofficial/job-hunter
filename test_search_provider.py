import os
import unittest
from unittest.mock import patch

from search_provider import SearchProviderError, SearchRateLimitError, configured_provider, search_urls


class SearchProviderTests(unittest.TestCase):
    def test_auto_selects_first_configured_provider(self):
        with patch.dict(os.environ, {"ATS_SEARCH_PROVIDER": "auto", "BRAVE_SEARCH_API_KEY": "test-key"}, clear=False):
            self.assertEqual(configured_provider(), "brave")

    def test_missing_provider_key_is_actionable(self):
        with patch.dict(os.environ, {"ATS_SEARCH_PROVIDER": "auto"}, clear=True):
            with self.assertRaisesRegex(SearchProviderError, "No ATS search provider configured"):
                search_urls("site:jobs.ashbyhq.com software India")

    @patch("search_provider.urlopen")
    def test_http_429_is_classified_for_circuit_breaker(self, urlopen):
        from urllib.error import HTTPError

        urlopen.side_effect = HTTPError("https://api.search.brave.com", 429, "rate limited", {}, None)
        with patch.dict(os.environ, {"ATS_SEARCH_PROVIDER": "brave", "BRAVE_SEARCH_API_KEY": "test-key"}, clear=False):
            with self.assertRaises(SearchRateLimitError):
                search_urls("site:jobs.ashbyhq.com software India")


if __name__ == "__main__":
    unittest.main()
