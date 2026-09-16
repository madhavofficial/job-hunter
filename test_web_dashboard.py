import io
import os
import unittest
from unittest.mock import MagicMock, patch
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
        self.assertIn("recommended_jobs", data)
        self.assertIn("discovery_jobs", data)
        self.assertIn("applied_jobs", data)
        self.assertIn("all_shortlisted", data)

        stats = data["stats"]
        for k in ["total_shortlisted", "recommended_count", "fresh_48h", "tier1_count", "total_applied"]:
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

    def test_safe_tailored_path_validation(self):
        tailored_dir = web_dashboard.TAILORED_DIR
        valid_pdf = os.path.join(tailored_dir, "test_resume.pdf")

        self.assertTrue(web_dashboard.is_safe_tailored_path(valid_pdf))
        self.assertFalse(web_dashboard.is_safe_tailored_path(tailored_dir))
        self.assertFalse(web_dashboard.is_safe_tailored_path("/etc/passwd"))
        self.assertFalse(web_dashboard.is_safe_tailored_path(os.path.join(tailored_dir, "../web_dashboard.py")))
        self.assertFalse(web_dashboard.is_safe_tailored_path("../../etc/passwd"))
        self.assertFalse(web_dashboard.is_safe_tailored_path(""))
        self.assertFalse(web_dashboard.is_safe_tailored_path(None))

    def test_pdf_endpoint_path_traversal_blocked(self):
        handler = web_dashboard.DashboardRequestHandler.__new__(web_dashboard.DashboardRequestHandler)
        handler.path = "/pdf?path=/etc/passwd"
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()

        handler.do_GET()
        handler.send_response.assert_called_with(403)

    def test_reveal_endpoint_path_traversal_blocked(self):
        handler = web_dashboard.DashboardRequestHandler.__new__(web_dashboard.DashboardRequestHandler)
        handler.path = "/api/reveal"
        handler.headers = {"Content-Length": "24"}
        handler.rfile = io.BytesIO(b'{"path": "/etc/passwd"}')
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()

        handler.do_POST()
        handler.send_response.assert_called_with(403)

    def test_database_and_dashboard_rankings_synchronized(self):
        # Synchronize database
        db.sync_shortlisted_rankings()

        # Check DB rankings
        conn = db.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT job_id, company, score, recommendation_status FROM jobs WHERE status = 'shortlisted' ORDER BY score DESC, created_at DESC")
        db_jobs = [dict(r) for r in cursor.fetchall()]
        conn.close()

        # Check Web Dashboard rankings
        dash_data = web_dashboard.get_dashboard_data()
        rec_jobs = dash_data["recommended_jobs"]
        all_shortlisted = dash_data["all_shortlisted"]

        # 1. Dashboard recommended jobs must be in strictly descending order
        rec_scores = [j["score"] for j in rec_jobs]
        self.assertEqual(rec_scores, sorted(rec_scores, reverse=True))

        # 2. All shortlisted jobs in dashboard must be in strictly descending score order
        all_scores = [j["score"] for j in all_shortlisted]
        self.assertEqual(all_scores, sorted(all_scores, reverse=True))

        # 3. The top recommended jobs in DB must match dashboard top recommended jobs
        db_recs = [j for j in db_jobs if j["recommendation_status"] == "recommended"]
        self.assertGreater(len(db_recs), 0)
        self.assertGreater(len(rec_jobs), 0)

        top_db_ids = [j["job_id"] for j in db_recs[:10]]
        top_dash_ids = [j["job_id"] for j in rec_jobs[:10]]
        self.assertEqual(top_db_ids, top_dash_ids)

        # 4. Underlying Decision Invariants: Every recommended job MUST satisfy:
        # - not Tier 3 (unverified)
        # - score >= 80
        # - recommendation_status == "recommended"
        for j in rec_jobs:
            self.assertEqual(j["recommendation_status"], "recommended")
            self.assertTrue(j["recommended"])
            self.assertGreaterEqual(j["score"], 80)
            self.assertFalse(j["tier"].startswith("Tier 3"), f"{j['company']} is Tier 3 but was recommended")

        # 5. Underlying Decision Invariants: No discovery job may be marked recommended
        for j in dash_data["discovery_jobs"]:
            self.assertNotEqual(j.get("recommendation_status"), "recommended")
            self.assertFalse(j.get("recommended", False))



if __name__ == "__main__":
    unittest.main()
