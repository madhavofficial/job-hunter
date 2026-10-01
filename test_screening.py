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

    def test_rejects_phd_title(self):
        ok, reason = deterministic_hard_filter({"title": "Software Engineering PhD Intern, Summer 2027", "company": "Google"})
        self.assertFalse(ok)
        self.assertIn("phd", reason.lower())

        ok, reason = deterministic_hard_filter({"title": "PhD Intern, AI ML in Wireless L1/L2", "company": "NVIDIA"})
        self.assertFalse(ok)
        self.assertIn("phd", reason.lower())

    def test_rejects_mba_title(self):
        ok, reason = deterministic_hard_filter({"title": "MBA Intern, Strategy & Operations", "company": "Amazon"})
        self.assertFalse(ok)
        self.assertIn("mba", reason.lower())

    def test_rejects_phd_enrollment_requirement(self):
        ok, reason = deterministic_hard_filter({
            "title": "AI Research Intern",
            "company": "DeepResearch",
            "description": "Must be currently enrolled in a PhD program in Computer Science or AI."
        })
        self.assertFalse(ok)
        self.assertIn("phd", reason.lower())

    def test_rejects_mba_in_description(self):
        ok, reason = deterministic_hard_filter({
            "title": "Business Analyst Intern",
            "company": "FinCorp",
            "description": "Must be currently enrolled in an MBA program or Master of Business Administration."
        })
        self.assertFalse(ok)
        self.assertIn("mba", reason.lower())

        ok, reason = deterministic_hard_filter({
            "title": "Operations Intern",
            "company": "LogisticsCo",
            "description": "MBA candidates only. Graduation year 2027."
        })
        self.assertFalse(ok)
        self.assertIn("mba", reason.lower())

    def test_unknown_company_tier3_discovery(self):
        # Unknown companies should be Tier 3 (unverified)
        self.assertEqual(classify_company_tier("Acme Robotics"), "Tier 3: Staffing Agency / Unverified")
        self.assertEqual(classify_company_tier("Random Labs"), "Tier 3: Staffing Agency / Unverified")

        # But they must still pass the deterministic hard filter into the discovery pool
        ok, reason = deterministic_hard_filter({
            "title": "Backend Intern",
            "company": "Acme Robotics",
            "location": "Bengaluru, India",
            "description": "Python and FastAPI development."
        })
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_normalize_job_title(self):
        from screening import normalize_job_title
        self.assertEqual(
            normalize_job_title("Software Engineer, Platform - Bangalore, India"),
            "Software Engineer, Platform"
        )
        self.assertEqual(
            normalize_job_title("Software Engineer, iOS Core Product - Ahmedabad, India"),
            "Software Engineer, iOS Core Product"
        )
        self.assertEqual(
            normalize_job_title("Full Stack Engineer (Bangalore)"),
            "Full Stack Engineer"
        )
        self.assertEqual(
            normalize_job_title("AI Engineer [Remote]"),
            "AI Engineer"
        )
        self.assertEqual(
            normalize_job_title("Backend Developer"),
            "Backend Developer"
        )

    def test_deduplicate_multi_location_jobs(self):
        from screening import deduplicate_multi_location_jobs
        jobs = [
            {"job_id": "1", "company": "Speechify", "title": "Software Engineer, Platform - Bangalore, India", "location": "Bangalore, India", "score": 85, "job_url_direct": "https://example.com/1"},
            {"job_id": "2", "company": "Speechify", "title": "Software Engineer, Platform - Mumbai, India", "location": "Mumbai, India", "score": 85, "job_url_direct": "https://example.com/2"},
            {"job_id": "3", "company": "Speechify", "title": "Software Engineer, Platform - Delhi, India", "location": "Delhi, India", "score": 85, "job_url_direct": "https://example.com/3"},
            {"job_id": "4", "company": "Google", "title": "Software Engineer Intern", "location": "Bengaluru, India", "score": 90, "job_url_direct": "https://example.com/4"},
        ]
        deduped = deduplicate_multi_location_jobs(jobs)
        self.assertEqual(len(deduped), 2)
        speechify_job = next(j for j in deduped if j["company"] == "Speechify")
        self.assertEqual(speechify_job["title"], "Software Engineer, Platform")
        self.assertIn("(+2 locations)", speechify_job["location"])


if __name__ == "__main__":
    unittest.main()

