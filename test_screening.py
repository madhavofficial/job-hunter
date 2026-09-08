import unittest

from screening import classify_company_tier, deterministic_hard_filter, is_job_truly_remote
from collector import SUPPORTED_INDIA_SITES


class ScreeningTests(unittest.TestCase):
    def test_india_sources_exclude_unsupported_boards(self):
        self.assertEqual(SUPPORTED_INDIA_SITES, ("indeed", "linkedin", "naukri"))
        self.assertNotIn("glassdoor", SUPPORTED_INDIA_SITES)
        self.assertNotIn("zip_recruiter", SUPPORTED_INDIA_SITES)

    def test_rejects_senior_title(self):
        ok, reason = deterministic_hard_filter({"title": "Senior AI Engineer", "company": "Acme"})
        self.assertFalse(ok)
        self.assertIn("senior", reason.lower())

    def test_rejects_explicit_experience_requirement(self):
        ok, reason = deterministic_hard_filter({"title": "Backend Engineer", "company": "Acme", "description": "Requires 5+ years of backend experience."})
        self.assertFalse(ok)
        self.assertIn("three years", reason)

    def test_rejects_wrong_graduation_batch(self):
        ok, reason = deterministic_hard_filter({"title": "Software Engineer Intern", "company": "Acme", "description": "Only eligible for 2026 batch graduates."})
        self.assertFalse(ok)
        self.assertIn("2027", reason)

    def test_rejects_unverified_company(self):
        self.assertTrue(classify_company_tier("Zenithbyte").startswith("Tier 3"))
        ok, _ = deterministic_hard_filter({"title": "Python Intern", "company": "Zenithbyte"})
        self.assertFalse(ok)

    def test_accepts_india_entry_role(self):
        ok, reason = deterministic_hard_filter({"title": "Backend Developer Intern", "company": "Acme", "location": "Bengaluru, India", "description": "Python and FastAPI."})
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_rejects_non_india_location(self):
        ok, reason = deterministic_hard_filter({"title": "Backend Developer", "company": "Acme", "location": "Toronto, Canada"})
        self.assertFalse(ok)
        self.assertIn("outside India", reason)

    def test_truly_remote_filtering(self):
        # Genuine remote roles
        self.assertTrue(is_job_truly_remote({"title": "Python Developer", "location": "Remote, IN"}))
        self.assertTrue(is_job_truly_remote({"title": "Full Stack Engineer (Remote)", "location": "India"}))
        self.assertTrue(is_job_truly_remote({"title": "Backend Intern", "location": "Work From Home"}))
        self.assertTrue(is_job_truly_remote({"title": "AI Intern", "location": "India", "description": "This is a 100% remote position."}))

        # Reject on-site/hybrid despite aggregator or title
        self.assertFalse(is_job_truly_remote({"title": "Full Stack Developer", "location": "Navi Mumbai, Maharashtra, India"}))
        self.assertFalse(is_job_truly_remote({"title": "Backend Developer", "location": "Ahmedabad, Gujarat, India"}))
        self.assertFalse(is_job_truly_remote({"title": "Python Developer", "location": "Bengaluru, Karnataka, India"}))
        self.assertFalse(is_job_truly_remote({"title": "Full Stack Developer (Hybrid)", "location": "Remote, IN"}))
        self.assertFalse(is_job_truly_remote({"title": "Software Engineer", "location": "Delhi (On-site)"}))
        self.assertFalse(is_job_truly_remote({"title": "Data Engineer", "location": "TS, IN"}))
        self.assertFalse(is_job_truly_remote({"title": "Software Developer", "location": ""}))


if __name__ == "__main__":
    unittest.main()
