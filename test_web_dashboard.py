import os
import unittest
from unittest.mock import patch
import db
import web_dashboard


class TestWebDashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    def test_dashboard_data_structure(self):
        data = web_dashboard.get_dashboard_data()
        self.assertIn("stats", data)
        self.assertIn("fresh_jobs", data)
        self.assertIn("applied_jobs", data)
        self.assertIn("all_shortlisted", data)

        stats = data["stats"]
        for k in ["total_shortlisted", "fresh_48h", "tier1_count", "total_applied"]:
            self.assertIn(k, stats)

        # Check fields in shortlisted jobs
        if data["all_shortlisted"]:
            sample = data["all_shortlisted"][0]
            self.assertIn("job_id", sample)
            self.assertIn("title", sample)
            self.assertIn("company", sample)
            self.assertIn("platform", sample)
            self.assertIn("status_portal_url", sample)

        # Check fields in applied jobs
        if data["applied_jobs"]:
            sample = data["applied_jobs"][0]
            self.assertIn("platform", sample)
            self.assertIn("status_portal_url", sample)

    def test_restore_and_dismiss_flow(self):
        test_job_id = "test_ux_job_12345"
        conn = db.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM jobs WHERE job_id = ?", (test_job_id,))
        cursor.execute("""
        INSERT INTO jobs (job_id, site, job_url, title, company, status, score)
        VALUES (?, 'custom', 'https://example.com/job', 'Staff AI Engineer', 'TestCo UX', 'shortlisted', 95)
        """, (test_job_id,))
        conn.commit()
        conn.close()

        try:
            # 1. Dismiss
            db.mark_as_rejected(test_job_id)
            conn = db.get_db_connection()
            c = conn.cursor()
            c.execute("SELECT status FROM jobs WHERE job_id = ?", (test_job_id,))
            self.assertEqual(c.fetchone()["status"], "rejected")
            conn.close()

            # 2. Restore
            conn = db.get_db_connection()
            c = conn.cursor()
            c.execute("UPDATE jobs SET status = 'shortlisted' WHERE job_id = ?", (test_job_id,))
            conn.commit()
            c.execute("SELECT status FROM jobs WHERE job_id = ?", (test_job_id,))
            self.assertEqual(c.fetchone()["status"], "shortlisted")
            conn.close()
        finally:
            conn = db.get_db_connection()
            c = conn.cursor()
            c.execute("DELETE FROM jobs WHERE job_id = ?", (test_job_id,))
            conn.commit()
            conn.close()

    def test_apply_flow_waits_for_confirmation_before_marking_applied(self):
        test_job_id = "test_confirmation_job_12345"
        task_id = "test_confirmation_task_12345"
        resume_path = "/tmp/test-resume.md"
        resume_pdf_path = "/tmp/test-resume.pdf"
        conn = db.get_db_connection()
        conn.execute("DELETE FROM jobs WHERE job_id = ?", (test_job_id,))
        conn.execute("""
        INSERT INTO jobs (job_id, site, job_url, title, company, status, score)
        VALUES (?, 'custom', 'https://example.com/job', 'Backend Engineer', 'TestCo', 'shortlisted', 90)
        """, (test_job_id,))
        conn.commit()
        conn.close()

        try:
            with patch.object(web_dashboard.tailor, "tailor_materials", return_value=(resume_path, resume_pdf_path)), \
                 patch.object(web_dashboard.webbrowser, "open", return_value=True):
                web_dashboard._run_tailor_worker(task_id, test_job_id, {
                    "job_url": "https://example.com/job",
                    "job_url_direct": "",
                    "title": "Backend Engineer",
                    "company": "TestCo",
                })

            conn = db.get_db_connection()
            self.assertEqual(
                conn.execute("SELECT status FROM jobs WHERE job_id = ?", (test_job_id,)).fetchone()["status"],
                "shortlisted",
            )
            conn.close()

            result = web_dashboard.finalize_application(task_id, test_job_id, "applied")
            self.assertEqual(result["application_status"], "applied")
            conn = db.get_db_connection()
            row = conn.execute(
                "SELECT status, tailored_resume_path, tailored_resume_pdf_path FROM jobs WHERE job_id = ?",
                (test_job_id,),
            ).fetchone()
            self.assertEqual(row["status"], "applied")
            self.assertEqual(row["tailored_resume_path"], resume_path)
            self.assertEqual(row["tailored_resume_pdf_path"], resume_pdf_path)
            conn.close()
        finally:
            with web_dashboard._apply_tasks_lock:
                web_dashboard._apply_tasks.pop(task_id, None)
            conn = db.get_db_connection()
            conn.execute("DELETE FROM jobs WHERE job_id = ?", (test_job_id,))
            conn.commit()
            conn.close()


if __name__ == "__main__":
    unittest.main()
