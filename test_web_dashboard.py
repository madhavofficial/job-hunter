import os
import unittest
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


if __name__ == "__main__":
    unittest.main()
