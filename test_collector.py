import unittest
from collector import DEFAULT_SEARCH_TERMS, TARGET_TECH_COMPANIES, get_dynamic_search_terms


class CollectorTests(unittest.TestCase):
    def test_default_search_terms_include_high_signal_roles(self):
        self.assertIn("Applied AI Engineer", DEFAULT_SEARCH_TERMS)
        self.assertIn("AI Engineer", DEFAULT_SEARCH_TERMS)
        self.assertIn("Software Development Engineer", DEFAULT_SEARCH_TERMS)
        self.assertIn("SDE 1", DEFAULT_SEARCH_TERMS)
        self.assertIn("Software Engineer Intern", DEFAULT_SEARCH_TERMS)

    def test_dynamic_search_terms_contain_unprefixed_roles(self):
        terms = get_dynamic_search_terms()
        self.assertIn("Applied AI Engineer", terms)
        self.assertIn("AI Engineer", terms)
        self.assertIn("Software Development Engineer", terms)
        self.assertIn("SDE 1", terms)
        self.assertIn("Software Engineer Intern", terms)
        # Should NOT only have "Junior" prefixed terms
        has_direct_ai = any(t in ("Applied AI Engineer", "AI Engineer") for t in terms)
        self.assertTrue(has_direct_ai)

    def test_target_tech_companies_include_tier1(self):
        self.assertIn("OpenAI", TARGET_TECH_COMPANIES)
        self.assertIn("Anthropic", TARGET_TECH_COMPANIES)
        self.assertIn("Google", TARGET_TECH_COMPANIES)
        self.assertIn("Microsoft", TARGET_TECH_COMPANIES)
        self.assertIn("Uber", TARGET_TECH_COMPANIES)
        self.assertIn("Razorpay", TARGET_TECH_COMPANIES)


if __name__ == "__main__":
    unittest.main()
