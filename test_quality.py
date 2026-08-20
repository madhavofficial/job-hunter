import os
import tempfile
import unittest

import pandas as pd

import db
from pdf_utils import markdown_to_pdf


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


if __name__ == "__main__":
    unittest.main()
