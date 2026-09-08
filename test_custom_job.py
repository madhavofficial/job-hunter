"""Unit tests for custom_job module."""

import unittest
from unittest.mock import MagicMock, patch

import custom_job
import db


class TestCustomJob(unittest.TestCase):
    def setUp(self):
        db.init_db()

    def test_extract_linkedin_id(self):
        url1 = "https://www.linkedin.com/jobs/view/4458726341/"
        self.assertEqual(custom_job.extract_linkedin_id(url1), "4458726341")
        url2 = "https://www.linkedin.com/jobs/collections/recommended/?currentJobId=4459114214"
        self.assertEqual(custom_job.extract_linkedin_id(url2), "4459114214")
        url3 = "https://example.com/careers/job-12345"
        self.assertIsNone(custom_job.extract_linkedin_id(url3))

    def test_ingest_custom_job_direct(self):
        custom_url = "https://careers.example.com/jobs/test-unique-unit-12345"
        custom_text = """
        Company: TestCorp AI
        Title: Senior AI Platform Engineer
        Location: Bengaluru, India
        Requirements: Python, LangChain, Distributed Systems, FastAPI, PostgreSQL.
        Responsibilities: Build scalable LLM microservices and agent workflows.
        """
        # Clean previous if any
        conn = db.get_db_connection()
        conn.execute("DELETE FROM jobs WHERE job_url = ?", (custom_url,))
        conn.commit()
        conn.close()

        job_id = custom_job.ingest_custom_job(custom_url, custom_text=custom_text)
        self.assertTrue(job_id.startswith("custom-") or job_id.startswith("li-"))
        conn = db.get_db_connection()
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["job_url"], custom_url)
        self.assertEqual(row["status"], "shortlisted")
        self.assertEqual(custom_job.ingest_custom_job(custom_url), job_id)


if __name__ == "__main__":
    unittest.main()
