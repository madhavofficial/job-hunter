"""Unit tests for GitHub portfolio integration."""

import unittest
import os
import json
import tempfile
from unittest.mock import patch
import github_portfolio


class TestGitHubPortfolio(unittest.TestCase):
    def test_get_github_username(self):
        user = github_portfolio.get_github_username()
        self.assertEqual(user, "madhavofficial")

    def test_fetch_and_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_cache = github_portfolio.CACHE_FILE
            original_home = github_portfolio.USER_HOME
            github_portfolio.CACHE_FILE = os.path.join(temp_dir, "portfolio.json")
            github_portfolio.USER_HOME = temp_dir
            repo_dir = os.path.join(temp_dir, "CareerTime")
            os.makedirs(repo_dir)
            with open(os.path.join(repo_dir, "README.md"), "w", encoding="utf-8") as stream:
                stream.write("# CareerTime\nCareer planning tool")
            response = type("Response", (), {
                "status_code": 200,
                "json": lambda self: [{
                    "name": "CareerTime", "fork": False, "description": "Career planning tool",
                    "language": "Python", "topics": ["career"],
                    "html_url": "https://github.com/madhavofficial/CareerTime",
                }],
            })()
            with patch.object(github_portfolio.requests, "get", return_value=response):
                portfolio = github_portfolio.fetch_github_portfolio(
                    username="madhavofficial", force_refresh=True
                )
            github_portfolio.CACHE_FILE = original_cache
            github_portfolio.USER_HOME = original_home

        self.assertIsInstance(portfolio, list)
        self.assertGreater(len(portfolio), 0)

        # Verify key projects exist in portfolio
        repo_names = {p["name"] for p in portfolio}
        self.assertTrue(
            "Ultimate-Trader-Dashboard-GitHub-Repository-Structure" in repo_names
            or "CareerTime" in repo_names
        )
        # Verify incomplete repos are excluded
        self.assertNotIn("secure-devops-scanner", repo_names)
        self.assertTrue(github_portfolio.is_repo_excluded("secure-devops-scanner"))
        self.assertTrue(github_portfolio.is_repo_excluded("securedevopsscanner"))

        # Check caching file exists
        self.assertTrue(os.path.exists(github_portfolio.CACHE_FILE))

    def test_formatting_for_prompt(self):
        sample_portfolio = [
            {
                "name": "secure-devops-scanner",
                "url": "https://github.com/madhavofficial/secure-devops-scanner",
                "language": "TypeScript",
                "topics": ["devops", "security"],
                "description": "AST codebase scanner and action pinner.",
                "readme_summary": "Features:\n- Local AST scanner\n- Semantic matching",
            }
        ]
        formatted = github_portfolio.format_github_portfolio_for_prompt(sample_portfolio)
        self.assertIn("secure-devops-scanner", formatted)
        self.assertIn("TypeScript", formatted)
        self.assertIn("https://github.com/madhavofficial/secure-devops-scanner", formatted)
        self.assertIn("AST codebase scanner", formatted)


if __name__ == "__main__":
    unittest.main()
