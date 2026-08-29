"""Unit tests for custom_job module."""

import unittest
import os
import tempfile
from unittest.mock import MagicMock, patch

import custom_job
import db


class TestCustomJob(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, "jobs.db")
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_extract_linkedin_id(self):
        url1 = "https://www.linkedin.com/jobs/view/4458726341/"
        self.assertEqual(custom_job.extract_linkedin_id(url1), "4458726341")

        url2 = "https://www.linkedin.com/jobs/collections/recommended/?currentJobId=4459114214"
        self.assertEqual(custom_job.extract_linkedin_id(url2), "4459114214")

        url3 = "https://example.com/careers/job-12345"
        self.assertIsNone(custom_job.extract_linkedin_id(url3))

    def test_ingest_custom_job_direct(self):
        custom_url = "https://careers.example.com/jobs/test-lead-ai-eng-999"
        custom_text = """
        Company: TestCorp AI
        Title: Junior AI Platform Engineer
        Location: Bengaluru, India
        Requirements: Python, LangChain, Distributed Systems, FastAPI, PostgreSQL.
        Responsibilities: Build scalable LLM microservices and agent workflows.
        """

        job_id = custom_job.ingest_custom_job(custom_url, custom_text=custom_text)
        self.assertTrue(job_id.startswith("custom-") or job_id.startswith("li-"))

        # Verify DB entry
        conn = db.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row["job_url"], custom_url)
        self.assertEqual(row["status"], "shortlisted")

        # Test deduplication
        job_id_repeat = custom_job.ingest_custom_job(custom_url)
        self.assertEqual(job_id, job_id_repeat)


if __name__ == "__main__":
    unittest.main()
