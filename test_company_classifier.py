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

    def test_dynamic_classification_caching(self):
        # Verify that dynamic classifications persist and are retrieved from cache
        norm = normalize_company_key("DynamicTechCo")
        save_classification(norm, "DynamicTechCo", "AI & Tech Startup", "high", "ai_search", "Dynamic AI resolution")
        result = get_company_category("DynamicTechCo", allow_network=False)
        self.assertEqual(result, "AI & Tech Startup")

    def test_failed_model_call_is_not_cached_as_unverified(self):
        import os
        import tempfile
        from unittest.mock import patch
        from company_classifier import UNVERIFIED_FALLBACK_REASON
        with tempfile.TemporaryDirectory() as tmp, patch.object(db, "DB_PATH", os.path.join(tmp, "jobs.db")), \
             patch("company_classifier.web_search_company_context", return_value=""):
            with patch("company_classifier.classify_with_ai",
                       return_value=("Staffing Agency / Unverified", UNVERIFIED_FALLBACK_REASON)):
                self.assertEqual(get_company_category("Maersk GSC (India) P.L."), "Staffing Agency / Unverified")
            self.assertIsNone(get_cached_classification(normalize_company_key("Maersk GSC (India) P.L.")))
            with patch("company_classifier.classify_with_ai",
                       return_value=("Big Tech & Global MNC", "Global shipping and logistics group.")):
                self.assertEqual(get_company_category("Maersk GSC (India) P.L."), "Big Tech & Global MNC")
            self.assertEqual(
                get_company_category("Maersk GSC (India) P.L.", allow_network=False), "Big Tech & Global MNC",
            )

    def test_shortlisted_unknown_employers_are_classified_and_reranked(self):
        import os
        import tempfile
        from unittest.mock import patch
        import matcher
        job = {
            "job_id": "wd-1", "site": "ats:workday", "title": "AI/ML Engineer",
            "company": "Maersk GSC (India) P.L.", "location": "India, Bengaluru, 560064; India",
            "job_url": "https://maersk.wd3.myworkdayjobs.com/maersk_careers/job/1",
            "job_url_direct": "https://maersk.wd3.myworkdayjobs.com/maersk_careers/job/1",
            "description": "Build ML services in Python for logistics platforms. " * 40,
            "status": "shortlisted", "score": 86, "role_fit_score": 92,
        }
        with tempfile.TemporaryDirectory() as tmp, patch.object(db, "DB_PATH", os.path.join(tmp, "jobs.db")):
            db.init_db()
            conn = db.get_db_connection()
            cols = ", ".join(job)
            conn.execute(f"INSERT INTO jobs ({cols}) VALUES ({', '.join('?' for _ in job)})", list(job.values()))
            conn.commit()
            conn.close()
            with patch("company_classifier.web_search_company_context", return_value=""), \
                 patch("company_classifier.classify_with_ai",
                       return_value=("Big Tech & Global MNC", "Global shipping and logistics group.")) as model:
                moved = matcher.classify_shortlisted_employers()
                again = matcher.classify_shortlisted_employers()
            conn = db.get_db_connection()
            row = conn.execute("SELECT recommendation_status FROM jobs WHERE job_id = 'wd-1'").fetchone()
            conn.close()
        self.assertEqual((moved, again, model.call_count), (1, 0, 1))
        self.assertEqual(row["recommendation_status"], "recommended")


if __name__ == "__main__":
    unittest.main()
