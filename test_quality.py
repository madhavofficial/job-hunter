import unittest
from datetime import datetime, timedelta

from quality import (
    assess_listing_quality,
    canonical_job_key,
    is_recommended_role,
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
        self.assertTrue(classify_company_tier("Infosys").startswith("Tier 2"))
        self.assertTrue(classify_company_tier("Coram AI").startswith("Tier 1"))
        self.assertTrue("Big Tech" in classify_company_tier("Teradata"))

    def test_missing_description_enters_review_pool_with_capped_score(self):
        job = self.make_job(description="")
        tier = classify_company_tier(job["company"])
        quality = assess_listing_quality(job, tier)
        passes, reason = quality_gate(job, tier, quality)
        self.assertTrue(passes, reason)
        score, _ = weighted_match_score(95, quality)
        self.assertLessEqual(score, 79)

    def test_unknown_direct_ats_employer_enters_discovery_but_not_tier_one(self):
        job = self.make_job(company="Mystery Labs")
        tier = classify_company_tier(job["company"])
        quality = assess_listing_quality(job, tier)
        passes, reason = quality_gate(job, tier, quality)
        self.assertTrue(passes, reason)
        self.assertTrue(tier.startswith("Tier 3"))
        self.assertEqual(quality["company_score"], 65)

    def test_unknown_aggregator_employer_enters_review_pool_with_cap(self):
        job = self.make_job(
            company="Mystery Labs",
            site="linkedin",
            job_url="https://www.linkedin.com/jobs/view/123",
            job_url_direct="https://www.linkedin.com/jobs/view/123",
        )
        tier = classify_company_tier(job["company"])
        quality = assess_listing_quality(job, tier)
        passes, reason = quality_gate(job, tier, quality)
        self.assertTrue(passes, reason)
        score, _ = weighted_match_score(95, quality)
        self.assertLessEqual(score, 84)

    def test_generic_title_with_partial_description_enters_review_pool(self):
        job = self.make_job(title="Software Engineer", description="Join our team. Freshers welcome.")
        tier = classify_company_tier(job["company"])
        quality = assess_listing_quality(job, tier)
        passes, reason = quality_gate(job, tier, quality)
        self.assertTrue(passes, reason)
        score, _ = weighted_match_score(95, quality)
        self.assertLessEqual(score, 79)

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

    def test_recommendation_decision_boundaries(self):
        # 1. Negative Control: Tier 3 (Unverified) must NEVER be recommended, even with 100% role fit & full JD
        unverified_job = self.make_job(company="Acme Robotics")
        tier3 = classify_company_tier(unverified_job["company"])
        self.assertTrue(tier3.startswith("Tier 3"))
        quality = assess_listing_quality(unverified_job, tier3)
        passes, _ = quality_gate(unverified_job, tier3, quality)
        score, _ = weighted_match_score(100, quality)
        self.assertFalse(is_recommended_role(passes, tier3, score, quality))

        # 2. Negative Control: Truncated description (< 700 chars / description_score < 80) must NEVER be recommended
        truncated_job = self.make_job(company="Google", description="Short job description.")
        tier1 = classify_company_tier(truncated_job["company"])
        self.assertTrue(tier1.startswith("Tier 1"))
        quality = assess_listing_quality(truncated_job, tier1)
        passes, _ = quality_gate(truncated_job, tier1, quality)
        score, _ = weighted_match_score(100, quality)
        self.assertLess(quality["description_score"], 80)
        self.assertFalse(is_recommended_role(passes, tier1, score, quality))

        # 3. Negative Control: Low compatibility score (< 80) must NEVER be recommended
        low_score_job = self.make_job(company="Google")
        tier1 = classify_company_tier(low_score_job["company"])
        quality = assess_listing_quality(low_score_job, tier1)
        passes, _ = quality_gate(low_score_job, tier1, quality)
        score, _ = weighted_match_score(50, quality)
        self.assertLess(score, 80)
        self.assertFalse(is_recommended_role(passes, tier1, score, quality))

        # 4. Negative Control: Quality Gate Failure (irrelevant title) must NEVER be recommended
        irrelevant_job = self.make_job(company="Google", title="Marketing Manager")
        tier1 = classify_company_tier(irrelevant_job["company"])
        quality = assess_listing_quality(irrelevant_job, tier1)
        passes, _ = quality_gate(irrelevant_job, tier1, quality)
        self.assertFalse(passes)
        self.assertFalse(is_recommended_role(passes, tier1, 95, quality))

        # 5. Positive Control: Tier 1 Big Tech + Full Description + Score >= 80 -> Recommended
        good_big_tech = self.make_job(company="Google")
        tier1 = classify_company_tier(good_big_tech["company"])
        quality = assess_listing_quality(good_big_tech, tier1)
        passes, _ = quality_gate(good_big_tech, tier1, quality)
        score, _ = weighted_match_score(90, quality)
        self.assertTrue(passes)
        self.assertGreaterEqual(score, 80)
        self.assertGreaterEqual(quality["description_score"], 80)
        self.assertTrue(is_recommended_role(passes, tier1, score, quality))

        # 6. Positive Control: Tier 1 AI Startup + Full Description + Score >= 80 -> Recommended
        good_startup = self.make_job(company="Coram AI")
        tier1 = classify_company_tier(good_startup["company"])
        quality = assess_listing_quality(good_startup, tier1)
        passes, _ = quality_gate(good_startup, tier1, quality)
        score, _ = weighted_match_score(90, quality)
        self.assertTrue(is_recommended_role(passes, tier1, score, quality))

        # 7. Positive Control: Tier 2 Global IT Services + Full Description + Score >= 80 -> Recommended
        good_it_services = self.make_job(company="Infosys")
        tier2 = classify_company_tier(good_it_services["company"])
        self.assertTrue(tier2.startswith("Tier 2"))
        quality = assess_listing_quality(good_it_services, tier2)
        passes, _ = quality_gate(good_it_services, tier2, quality)
        score, _ = weighted_match_score(90, quality)
        self.assertTrue(is_recommended_role(passes, tier2, score, quality))


if __name__ == "__main__":
    unittest.main()
