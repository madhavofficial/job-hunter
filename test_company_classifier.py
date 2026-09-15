import unittest
import sqlite3
from company_classifier import (
    get_company_category,
    get_cached_classification,
    save_classification,
    normalize_company_key,
    init_classification_table,
    CANONICAL_CATEGORIES,
)
import db


class CompanyClassifierTests(unittest.TestCase):
    def setUp(self):
        conn = db.get_db_connection()
        try:
            init_classification_table(conn)
        finally:
            conn.close()

    def test_known_big_tech_classification(self):
        self.assertEqual(get_company_category("Google", allow_network=False), "Big Tech & Global MNC")
        self.assertEqual(get_company_category("Microsoft", allow_network=False), "Big Tech & Global MNC")
        self.assertEqual(get_company_category("NatWest Group", allow_network=False), "Big Tech & Global MNC")
        self.assertEqual(get_company_category("Hewlett Packard Enterprise", allow_network=False), "Big Tech & Global MNC")

    def test_known_unicorn_classification(self):
        self.assertEqual(get_company_category("OpenAI", allow_network=False), "Unicorn / Tech Giant")
        self.assertEqual(get_company_category("Stripe", allow_network=False), "Unicorn / Tech Giant")
        self.assertEqual(get_company_category("Swiggy", allow_network=False), "Unicorn / Tech Giant")
        self.assertEqual(get_company_category("Zomato", allow_network=False), "Unicorn / Tech Giant")
        self.assertEqual(get_company_category("Razorpay", allow_network=False), "Unicorn / Tech Giant")

    def test_known_it_services_classification(self):
        self.assertEqual(get_company_category("Tata Consultancy Services", allow_network=False), "IT Services & Consultancies")
        self.assertEqual(get_company_category("Infosys", allow_network=False), "IT Services & Consultancies")
        self.assertEqual(get_company_category("Capgemini", allow_network=False), "IT Services & Consultancies")
        self.assertEqual(get_company_category("Wipro", allow_network=False), "IT Services & Consultancies")
        self.assertEqual(get_company_category("Accenture", allow_network=False), "IT Services & Consultancies")

    def test_known_staffing_agency_classification(self):
        self.assertEqual(get_company_category("Zenithbyte", allow_network=False), "Staffing Agency / Unverified")
        self.assertEqual(get_company_category("Randstad", allow_network=False), "Staffing Agency / Unverified")
        self.assertEqual(get_company_category("Michael Page", allow_network=False), "Staffing Agency / Unverified")

    def test_sqlite_cache_roundtrip(self):
        test_comp = "UniqueTestCo123"
        norm = normalize_company_key(test_comp)
        save_classification(norm, test_comp, "Unicorn / Tech Giant", "high", "test", "Unit test cached entry")
        cached = get_cached_classification(norm)
        self.assertIsNotNone(cached)
        self.assertEqual(cached["category"], "Unicorn / Tech Giant")
        self.assertEqual(cached["confidence"], "high")
        self.assertEqual(cached["source"], "test")

    def test_empty_company_handling(self):
        result = get_company_category("", allow_network=False)
        self.assertEqual(result, "Staffing Agency / Unverified")

    def test_unknown_company_handling_offline(self):
        # Unknown employers should be classified as unverified/discovery-only when offline
        self.assertEqual(get_company_category("Acme Robotics", allow_network=False), "Staffing Agency / Unverified")
        self.assertEqual(get_company_category("Random Labs", allow_network=False), "Staffing Agency / Unverified")
        self.assertEqual(get_company_category("Unknown Stealth Co", allow_network=False), "Staffing Agency / Unverified")

    def test_punctuation_normalization_and_ampersand(self):
        self.assertEqual(get_company_category("AT&T", allow_network=False), "Big Tech & Global MNC")
        self.assertEqual(get_company_category("at&t", allow_network=False), "Big Tech & Global MNC")
        self.assertEqual(get_company_category("Johnson & Johnson", allow_network=False), "Big Tech & Global MNC")
        self.assertEqual(get_company_category("L&T Technology Services", allow_network=False), "IT Services & Consultancies")
        self.assertEqual(get_company_category("AtkinsRéalis", allow_network=False), "Big Tech & Global MNC")

    def test_seed_precedence_over_stale_cache(self):
        # Plant a stale / incorrect cache row for Google
        norm = normalize_company_key("Google")
        save_classification(norm, "Google", "Staffing Agency / Unverified", "low", "stale_bot", "Erroneous cache")
        cached = get_cached_classification(norm)
        self.assertEqual(cached["category"], "Staffing Agency / Unverified")

        # Calling get_company_category should prioritize the curated seed over the stale cache entry
        result = get_company_category("Google", allow_network=False)
        self.assertEqual(result, "Big Tech & Global MNC")

        # And verify that the cache was corrected
        refreshed = get_cached_classification(norm)
        self.assertEqual(refreshed["category"], "Big Tech & Global MNC")
        self.assertEqual(refreshed["source"], "seed")


if __name__ == "__main__":
    unittest.main()
