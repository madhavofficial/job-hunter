import os
import unittest
from unittest.mock import patch, MagicMock
import profiles
import tailor
import github_portfolio


class ProfileUnitTests(unittest.TestCase):
    def test_default_profile_is_madhav(self):
        p = profiles.get_profile()
        self.assertEqual(p.id, "madhav")
        self.assertEqual(p.name, "Madhav Jayam")
        self.assertEqual(p.file_prefix, "Madhav_Jayam")
        self.assertFalse(p.include_gpa)
        self.assertIn("Do NOT include GPA", p.gpa_instruction)
        self.assertEqual(p.github_user, "madhavofficial")

    def test_mahika_profile(self):
        p = profiles.get_profile("mahika")
        self.assertEqual(p.id, "mahika")
        self.assertEqual(p.name, "Mahika Neranjen")
        self.assertEqual(p.file_prefix, "Mahika_Neranjen")
        self.assertTrue(p.include_gpa)
        self.assertIn("8.06", p.gpa_text)
        self.assertIn("ALWAYS INCLUDE", p.gpa_instruction)
        self.assertIn("8.06", p.gpa_instruction)
        self.assertEqual(p.github_user, "Mahika6")
        self.assertIn("capstone", p.known_project_urls)
        self.assertIn("neuro_capstone", p.known_project_urls["capstone"])
        self.assertIn("resume", p.known_project_urls)
        self.assertIn("genai-project", p.known_project_urls["resume"])

    def test_list_profiles(self):
        profile_list = profiles.list_profiles()
        ids = [x["id"] for x in profile_list]
        self.assertIn("madhav", ids)
        self.assertIn("mahika", ids)

    def test_mahika_project_github_link_injection(self):
        p_mahika = profiles.get_profile("mahika")
        markdown = """# Mahika Neranjen
## Selected Projects
### Capstone Project: AI for Neurodegenerative Protein Analysis
- High-recall biophysical reasoning pipeline.
"""
        portfolio = [
            {
                "name": "genai-project",
                "display_name": "Capstone Project: AI for Neurodegenerative Protein Analysis",
                "url": "https://github.com/Mahika6/genai-project"
            }
        ]
        result = tailor.ensure_selected_project_github_links(markdown, portfolio, profile=p_mahika)
        self.assertIn("*GitHub: https://github.com/Mahika6/genai-project*", result)

    def test_resume_naming_for_mahika(self):
        p_mahika = profiles.get_profile("mahika")
        clean_company = "Google"
        clean_title = "Software_Engineer"
        resume_filename = f"{p_mahika.file_prefix}_{clean_company}_{clean_title}_Resume.md"
        resume_pdf_filename = f"{p_mahika.file_prefix}_{clean_company}_{clean_title}_Resume.pdf"
        self.assertEqual(resume_filename, "Mahika_Neranjen_Google_Software_Engineer_Resume.md")
        self.assertEqual(resume_pdf_filename, "Mahika_Neranjen_Google_Software_Engineer_Resume.pdf")

    def test_portfolio_curated_projects_for_mahika(self):
        p_mahika = profiles.get_profile("mahika")
        portfolio = github_portfolio.fetch_github_portfolio(profile=p_mahika)
        names = [p.get("name") for p in portfolio]
        # DRDO is an internship, NOT a curated project
        self.assertNotIn("AI-Radar-Emitter-Identification", names)
        # Should contain her projects like Resume-JD-Semantic-Matcher and Visual-Odometry-Fire-Detection
        self.assertIn("Resume-JD-Semantic-Matcher", names)
        self.assertIn("Visual-Odometry-Fire-Detection", names)

    def test_strip_certifications(self):
        md = """# Candidate
## Experience
Worked here.

## Certifications
- HackerRank - Problem Solving
- MyCaptain - Generative AI

---
*Prepared for Deloitte*
"""
        stripped = tailor.strip_certifications(md)
        self.assertNotIn("HackerRank", stripped)
        self.assertNotIn("MyCaptain", stripped)
        self.assertNotIn("Certifications", stripped)
        self.assertIn("Worked here.", stripped)
        self.assertIn("*Prepared for Deloitte*", stripped)

    def test_unverified_github_link_is_stripped_from_project_without_repo(self):
        p_mahika = profiles.get_profile("mahika")
        md = """## Selected Projects
### Proprietary Kernel Driver (C, Systems)
*GitHub: https://github.com/Mahika6/Portfolio*
- What it does: Experimental kernel driver without public repo.
"""
        portfolio = [
            {"name": "Proprietary-Kernel-Driver", "url": None}
        ]
        result = tailor.ensure_selected_project_github_links(md, portfolio, profile=p_mahika)
        self.assertNotIn("Portfolio", result)
        self.assertNotIn("*GitHub:", result)
        self.assertIn("What it does: Experimental kernel driver without public repo.", result)

    def test_mini_unionfs_github_link_is_verified(self):
        p_mahika = profiles.get_profile("mahika")
        md = """## Selected Projects
### Mini-UnionFS File System (C, FUSE)
- What it does: Lightweight union file system in C.
"""
        portfolio = [
            {"name": "Mini-UnionFS", "url": "https://github.com/Mahika6/mini-unionfs"}
        ]
        result = tailor.ensure_selected_project_github_links(md, portfolio, profile=p_mahika)
        self.assertIn("*GitHub: https://github.com/Mahika6/mini-unionfs*", result)


    def test_madhav_curated_projects_and_master_resume(self):
        p_madhav = profiles.get_profile("madhav")
        self.assertEqual(len(p_madhav.curated_projects), 8)
        self.assertIn("neuro_capstone", p_madhav.curated_projects)
        self.assertIn("evidence-grounded-clinical-literature-synthesis", p_madhav.curated_projects)
        self.assertIn("153_Project3_BD", p_madhav.curated_projects)
        self.assertIn("Drawing-A-New-Way-To-Search-ML-", p_madhav.curated_projects)
        self.assertIn("CareerTime", p_madhav.curated_projects)
        self.assertIn("job-hunter", p_madhav.curated_projects)
        self.assertIn("Ultimate-Trader-Dashboard-GitHub-Repository-Structure", p_madhav.curated_projects)
        self.assertIn("Forecasting-Bike-Rental-Demand", p_madhav.curated_projects)

        with open(p_madhav.resume_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("Certifications", content)
        self.assertNotIn("HackerRank", content)
        self.assertIn("Multi-Modal AI Protein Analysis", content)
        self.assertIn("GLAS-Med", content)
        self.assertIn("153_Project3_BD", content)
        self.assertIn("Sketch Recognition System", content)
        self.assertIn("CareerTime", content)
        self.assertIn("Autonomous Job Discovery", content)
        self.assertIn("Smart Market Watchlist", content)
        self.assertIn("Hourly Bike-Sharing Demand Forecasting", content)
        self.assertIn("Career Objective", content)


if __name__ == "__main__":
    unittest.main()

