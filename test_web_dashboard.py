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
        self.assertIn("today_jobs", data)
        self.assertIsInstance(data["today_jobs"], list)
        self.assertIn("fresh_jobs", data)
        self.assertIn("recommended_jobs", data)
        self.assertIn("discovery_jobs", data)
        self.assertIn("applied_jobs", data)
        self.assertIn("all_shortlisted", data)

        stats = data["stats"]
        for k in ["total_shortlisted", "recommended_count", "discovered_today", "total_discovered_today", "fresh_48h", "tier1_count", "total_applied"]:
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
                 patch.object(web_dashboard.webbrowser, "open", return_value=True), \
                 patch("notion_sync.sync_applied_to_notion", return_value=1):
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

    def test_mark_applied_endpoint(self):
        import json
        test_job_id = "test_direct_mark_applied_999"
        conn = db.get_db_connection()
        conn.execute("DELETE FROM jobs WHERE job_id = ?", (test_job_id,))
        conn.execute("""
        INSERT INTO jobs (job_id, site, job_url, title, company, status, score, tailored_resume_pdf_path)
        VALUES (?, 'custom', 'https://example.com/direct-apply', 'AI Scientist', 'FutureCo', 'shortlisted', 95, '/path/to/pdf.pdf')
        """, (test_job_id,))
        conn.commit()
        conn.close()

        try:
            handler = web_dashboard.DashboardRequestHandler.__new__(web_dashboard.DashboardRequestHandler)
            handler.path = "/api/mark-applied"
            body = json.dumps({"job_id": test_job_id}).encode("utf-8")
            handler.headers = {"Content-Length": str(len(body))}
            handler.rfile = io.BytesIO(body)
            handler.send_response = MagicMock()
            handler.send_header = MagicMock()
            handler.end_headers = MagicMock()
            handler.wfile = io.BytesIO()

            with patch("notion_sync.sync_applied_to_notion", return_value=1):
                handler.do_POST()

            handler.send_response.assert_called_with(200)
            res = json.loads(handler.wfile.getvalue().decode("utf-8"))
            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("status"), "applied")

            conn = db.get_db_connection()
            row = conn.execute("SELECT status, tailored_resume_pdf_path FROM jobs WHERE job_id = ?", (test_job_id,)).fetchone()
            self.assertEqual(row["status"], "applied")
            self.assertEqual(row["tailored_resume_pdf_path"], "/path/to/pdf.pdf")
            conn.close()
        finally:
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

    def test_profiles_endpoint(self):
        import json
        handler = web_dashboard.DashboardRequestHandler.__new__(web_dashboard.DashboardRequestHandler)
        handler.path = "/api/profiles"
        handler.wfile = io.BytesIO()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        handler.do_GET()

        handler.send_response.assert_called_with(200)
        data = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertIsInstance(data, list)
        profile_ids = [p["id"] for p in data]
        self.assertIn("madhav", profile_ids)
        self.assertIn("mahika", profile_ids)

    def test_apply_worker_passes_profile(self):
        task_id = "test_profile_task_555"
        test_job_id = "test_profile_job_555"
        resume_path = "/tmp/Mahika_Neranjen_Test_Resume.md"
        resume_pdf_path = "/tmp/Mahika_Neranjen_Test_Resume.pdf"

        with patch.object(web_dashboard.tailor, "tailor_materials", return_value=(resume_path, resume_pdf_path)) as mock_tailor, \
             patch.object(web_dashboard.webbrowser, "open", return_value=True):
            web_dashboard._run_tailor_worker(task_id, test_job_id, {
                "job_url": "https://example.com/job",
                "title": "Data Scientist",
                "company": "DeepTech",
            }, profile_name="mahika")

            mock_tailor.assert_called_once_with(test_job_id, profile_name="mahika")

        with web_dashboard._apply_tasks_lock:
            task = web_dashboard._apply_tasks.pop(task_id, None)
            self.assertIsNotNone(task)
            self.assertEqual(task["status"], "done")
            self.assertEqual(task["result"]["resume_pdf_path"], resume_pdf_path)

    def test_upload_jd_pdf_endpoint_validation(self):
        import base64
        import json

        # 1. Missing pdf_base64
        handler = web_dashboard.DashboardRequestHandler.__new__(web_dashboard.DashboardRequestHandler)
        handler.path = "/api/upload-jd-pdf"
        handler.headers = {"Content-Length": "2"}
        handler.rfile = io.BytesIO(b'{}')
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = io.BytesIO()

        handler.do_POST()
        handler.send_response.assert_called_with(400)
        res = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertIn("error", res)

        # 2. Valid PDF upload with sync=True
        fake_pdf_b64 = base64.b64encode(b"%PDF-1.4 test pdf content").decode("ascii")
        payload = json.dumps({
            "filename": "Anthropic_AI_Engineer.pdf",
            "pdf_base64": fake_pdf_b64,
            "profile": "madhav",
            "sync": True
        }).encode("utf-8")

        handler = web_dashboard.DashboardRequestHandler.__new__(web_dashboard.DashboardRequestHandler)
        handler.path = "/api/upload-jd-pdf"
        handler.headers = {"Content-Length": str(len(payload))}
        handler.rfile = io.BytesIO(payload)
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = io.BytesIO()

        mock_job_row = {
            "job_id": "pdf-test12345",
            "title": "Staff AI Engineer",
            "company": "Anthropic",
            "score": 95
        }

        with patch("custom_job.ingest_pdf_job", return_value=("pdf-test12345", mock_job_row)), \
             patch.object(web_dashboard.tailor, "tailor_materials", return_value=("/tmp/resume.md", "/tmp/resume.pdf")):
            handler.do_POST()
            handler.send_response.assert_called_with(200)
            res = json.loads(handler.wfile.getvalue().decode("utf-8"))
            self.assertTrue(res["success"])
            self.assertEqual(res["job_id"], "pdf-test12345")
            self.assertEqual(res["title"], "Staff AI Engineer")
            self.assertEqual(res["company"], "Anthropic")

    def test_custom_job_endpoint_triggers_tailoring(self):
        import json
        handler = web_dashboard.DashboardRequestHandler.__new__(web_dashboard.DashboardRequestHandler)
        handler.path = "/api/custom"
        payload = json.dumps({
            "url": "https://www.linkedin.com/jobs/view/4471488562/",
            "profile": "madhav"
        }).encode("utf-8")
        handler.headers = {"Content-Length": str(len(payload))}
        handler.rfile = io.BytesIO(payload)
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = io.BytesIO()

        with patch("custom_job.ingest_custom_job", return_value="li-4471488562") as mock_ingest, \
             patch.object(web_dashboard.tailor, "tailor_materials", return_value=("/tmp/r.md", "/tmp/r.pdf")) as mock_tailor:
            handler.do_POST()
            handler.send_response.assert_called_with(200)
            mock_ingest.assert_called_once_with("https://www.linkedin.com/jobs/view/4471488562/", custom_text=None)
            mock_tailor.assert_called_once_with("li-4471488562", profile_name="madhav")
            res = json.loads(handler.wfile.getvalue().decode("utf-8"))
            self.assertTrue(res["success"])
            self.assertEqual(res["job_id"], "li-4471488562")
            self.assertEqual(res["resume_pdf_path"], "/tmp/r.pdf")

    def test_custom_job_endpoint_pasted_text_without_url(self):
        import json
        handler = web_dashboard.DashboardRequestHandler.__new__(web_dashboard.DashboardRequestHandler)
        handler.path = "/api/custom"
        payload = json.dumps({
            "url": None,
            "text": "Role: Backend Engineer\nCompany: Acme Labs\nStack: Python, FastAPI",
            "profile": "madhav"
        }).encode("utf-8")
        handler.headers = {"Content-Length": str(len(payload))}
        handler.rfile = io.BytesIO(payload)
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = io.BytesIO()

        with patch("custom_job.ingest_custom_job", return_value="custom-text-1234567890") as mock_ingest, \
             patch.object(web_dashboard.tailor, "tailor_materials", return_value=("/tmp/r.md", "/tmp/r.pdf")) as mock_tailor:
            handler.do_POST()
            handler.send_response.assert_called_with(200)
            mock_ingest.assert_called_once_with(None, custom_text="Role: Backend Engineer\nCompany: Acme Labs\nStack: Python, FastAPI")
            mock_tailor.assert_called_once_with("custom-text-1234567890", profile_name="madhav")
            res = json.loads(handler.wfile.getvalue().decode("utf-8"))
            self.assertTrue(res["success"])
            self.assertEqual(res["job_id"], "custom-text-1234567890")
            self.assertEqual(res["resume_pdf_path"], "/tmp/r.pdf")

    def test_discovered_today_bucket(self):
        from datetime import datetime, timedelta
        conn = db.get_db_connection()
        c = conn.cursor()
        today_id = "test_today_job_9999"
        old_id = "test_old_job_9999"
        today_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        old_str = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")

        c.execute("DELETE FROM jobs WHERE job_id IN (?, ?)", (today_id, old_id))
        c.execute("""
        INSERT INTO jobs (job_id, site, job_url, title, company, status, score, created_at)
        VALUES (?, 'greenhouse', 'https://job.today', 'AI Research Scientist', 'OpenAI', 'shortlisted', 98, ?)
        """, (today_id, today_str))
        c.execute("""
        INSERT INTO jobs (job_id, site, job_url, title, company, status, score, created_at)
        VALUES (?, 'lever', 'https://job.old', 'Platform Engineer', 'OldCo', 'shortlisted', 85, ?)
        """, (old_id, old_str))
        conn.commit()
        conn.close()

        try:
            data = web_dashboard.get_dashboard_data()
            today_job_ids = [j["job_id"] for j in data["today_jobs"]]
            self.assertIn(today_id, today_job_ids)
            self.assertNotIn(old_id, today_job_ids)
            self.assertGreaterEqual(data["stats"]["discovered_today"], 1)
        finally:
            conn = db.get_db_connection()
            c = conn.cursor()
            c.execute("DELETE FROM jobs WHERE job_id IN (?, ?)", (today_id, old_id))
            conn.commit()
            conn.close()

    def test_pipeline_run_preserves_previous_run_when_pipeline_not_yet_run_today(self):
        data = web_dashboard.get_dashboard_data()
        self.assertIn("last_pipeline_date", data["stats"])
        self.assertTrue(len(data["stats"]["last_pipeline_date"]) >= 10)
        # If there are jobs from the latest run, today_jobs must not be empty
        if data["stats"]["discovered_today"] > 0:
            self.assertGreater(len(data["today_jobs"]), 0)


if __name__ == "__main__":
    unittest.main()
