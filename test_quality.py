import os
import tempfile
import unittest

import pandas as pd

import db
from pdf_utils import markdown_to_pdf
from quality import apply_skill_gap_penalty, classify_job_tier, has_usable_description, passes_shortlist_policy


class QualityOfLifeTests(unittest.TestCase):
    def test_pdf_renderer_writes_pdf(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = os.path.join(temp_dir, "resume.pdf")
            markdown_to_pdf("# Madhav Jayam\n\n## Education\n- PES University\n\n## Experience\nBackend engineering", output)
            self.assertTrue(os.path.isfile(output))
            with open(output, "rb") as stream:
                self.assertEqual(stream.read(5), b"%PDF-")

    def test_pdf_text_normalizes_ats_unsafe_unicode(self):
        from pdf_utils import _plain_markdown
        rendered = _plain_markdown("Backend — AI-powered ‘platform’")
        self.assertEqual(rendered, "Backend - AI-powered &#x27;platform&#x27;")

    def test_direct_ats_source_replaces_aggregator_duplicate(self):
        original_db_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as temp_dir:
            db.DB_PATH = os.path.join(temp_dir, "jobs.db")
            db.init_db()
            db.add_jobs(pd.DataFrame([{
                "id": "linkedin-1", "site": "linkedin", "title": "Backend Engineer",
                "company": "Acme", "job_url": "https://example.com/aggregator",
                "job_url_direct": "https://example.com/aggregator", "location": "India",
                "description": "reposted description", "is_remote": False,
            }]))
            db.add_jobs(pd.DataFrame([{
                "id": "gh-1", "site": "ats:greenhouse", "title": "Backend Engineer",
                "company": "Acme", "job_url": "https://boards.greenhouse.io/acme/jobs/1",
                "job_url_direct": "https://boards.greenhouse.io/acme/jobs/1", "location": "India",
                "description": "canonical description", "is_remote": False,
            }]))
            with db.get_db_connection() as conn:
                row = conn.execute("SELECT job_id, site, job_url_direct, description FROM jobs").fetchone()
            self.assertEqual(dict(row), {
                "job_id": "linkedin-1",
                "site": "ats:greenhouse",
                "job_url_direct": "https://boards.greenhouse.io/acme/jobs/1",
                "description": "canonical description",
            })
        db.DB_PATH = original_db_path

    def test_unknown_aggregator_is_not_presented_as_tier_one(self):
        self.assertTrue(classify_job_tier({"company": "Mystery Labs", "site": "linkedin"}).startswith("Tier 3"))
        self.assertTrue(classify_job_tier({"company": "OpenAI", "site": "linkedin"}).startswith("Tier 1"))
        self.assertTrue(classify_job_tier({"company": "New ATS Company", "site": "ats:greenhouse"}).startswith("Tier 1"))
        self.assertTrue(classify_job_tier({"company": "TrustFabric", "site": "indeed"}).startswith("Tier 3"))

    def test_short_descriptions_are_not_matchable(self):
        self.assertFalse(has_usable_description({"description": "Backend engineer"}))
        self.assertTrue(has_usable_description({"description": "x" * 120}))

    def test_missing_headline_technology_caps_match_score(self):
        score, note = apply_skill_gap_penalty(
            90,
            {"title": "Java FS Angular Developer"},
            "Python, Java, JavaScript, React, Node.js",
        )
        self.assertEqual(score, 68)
        self.assertIn("Angular", note)

    def test_shortlist_policy_prioritizes_large_product_companies(self):
        self.assertTrue(passes_shortlist_policy({"company": "OpenAI"}, True, 42))
        self.assertTrue(passes_shortlist_policy({"company": "Small Product Labs"}, True, 70))
        self.assertFalse(passes_shortlist_policy({"company": "Small Product Labs"}, True, 69))
        self.assertFalse(passes_shortlist_policy({"company": "OpenAI"}, False, 99))


if __name__ == "__main__":
    unittest.main()
