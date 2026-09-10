import unittest
from datetime import datetime, timedelta

from quality import (
    assess_listing_quality,
    canonical_job_key,
    quality_gate,
    weighted_match_score,
)
from screening import classify_company_tier


class ListingQualityTests(unittest.TestCase):
    def make_job(self, **overrides):
        job = {
            "title": "Backend Engineer",
            "company": "Coram AI",
            "location": "Bengaluru, India",
            "site": "ats:greenhouse",
            "job_url": "https://boards.greenhouse.io/coram/jobs/1",
            "job_url_direct": "https://boards.greenhouse.io/coram/jobs/1",
            "description": (
                "Build and maintain backend services for our AI platform. Work with Python, APIs, "
                "databases, testing, deployment, and cross-functional engineering teams. "
                "Candidates should be current students or early-career engineers in India. "
            ) * 4,
            "skills": "Python, APIs, databases",
            "experience_range": "0-2 years",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        job.update(overrides)
        return job

    def test_unknown_company_is_not_auto_tier_one(self):
        self.assertTrue(classify_company_tier("Mystery Labs").startswith("Tier 3"))
        self.assertTrue(classify_company_tier("Teradata").startswith("Tier 2"))
        self.assertTrue(classify_company_tier("Coram AI").startswith("Tier 1"))

    def test_missing_description_is_rejected_before_scoring(self):
        job = self.make_job(description="")
        tier = classify_company_tier(job["company"])
        quality = assess_listing_quality(job, tier)
        passes, reason = quality_gate(job, tier, quality)
        self.assertFalse(passes)
        self.assertIn("Missing job description", reason)

    def test_unknown_direct_ats_employer_enters_discovery_but_not_tier_one(self):
        job = self.make_job(company="Mystery Labs")
        tier = classify_company_tier(job["company"])
        quality = assess_listing_quality(job, tier)
        passes, reason = quality_gate(job, tier, quality)
        self.assertTrue(passes, reason)
        self.assertTrue(tier.startswith("Tier 3"))
        self.assertEqual(quality["company_score"], 65)

    def test_unknown_aggregator_employer_is_rejected(self):
        job = self.make_job(
            company="Mystery Labs",
            site="linkedin",
            job_url="https://www.linkedin.com/jobs/view/123",
            job_url_direct="https://www.linkedin.com/jobs/view/123",
        )
        tier = classify_company_tier(job["company"])
        quality = assess_listing_quality(job, tier)
        passes, _ = quality_gate(job, tier, quality)
        self.assertFalse(passes)

    def test_generic_title_with_partial_description_is_rejected(self):
        job = self.make_job(title="Software Engineer", description="Join our team. Freshers welcome.")
        tier = classify_company_tier(job["company"])
        quality = assess_listing_quality(job, tier)
        passes, _ = quality_gate(job, tier, quality)
        self.assertFalse(passes)

    def test_partial_evidence_caps_final_score(self):
        job = self.make_job(description=("Build software with Python and APIs. " * 10))
        tier = classify_company_tier(job["company"])
        quality = assess_listing_quality(job, tier)
        score, components = weighted_match_score(95, quality)
        self.assertLessEqual(score, 79)
        self.assertEqual(components["role_fit"], 95)

    def test_canonical_key_normalizes_company_suffix_and_title_level(self):
        first = self.make_job(company="Acme Technologies Pvt Ltd", title="Backend Engineer II")
        second = self.make_job(company="Acme Technologies", title="Backend Engineer")
        self.assertEqual(canonical_job_key(first), canonical_job_key(second))

    def test_stale_roles_receive_lower_freshness(self):
        job = self.make_job(created_at=(datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S"))
        quality = assess_listing_quality(job, classify_company_tier(job["company"]))
        self.assertLess(quality["freshness_score"], 50)


if __name__ == "__main__":
    unittest.main()
