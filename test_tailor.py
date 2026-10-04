import unittest
from tailor import ensure_career_objective_target, ensure_selected_project_github_links, is_job_description_ambiguous, strip_meta_commentary


class AmbiguousJDTests(unittest.TestCase):
    def test_hp_idc_detected_as_ambiguous(self):
        title = "India Development Centre - IDC"
        description = (
            "HP is seeking talent for its India Development Centre (IDC) to drive innovative consumer technology solutions. "
            "This general listing outlines multiple potential roles across product management, user experience, embedded AI, "
            "Android development, camera engineering, device security, system software integration, and testing automation. "
            "Candidates will be considered as openings arise, with the aim of building products that impact millions globally."
        )
        is_ambig, reason = is_job_description_ambiguous(title, description)
        self.assertTrue(is_ambig)
        self.assertIn("multiple potential roles", reason.lower())

    def test_rotational_and_pooling_detected_as_ambiguous(self):
        title = "Graduate Engineer Trainee - Rotational Program"
        description = "Join our early career rotational talent pool where you will explore different areas across software systems."
        is_ambig, reason = is_job_description_ambiguous(title, description)
        self.assertTrue(is_ambig)

    def test_cross_disciplinary_multi_domain_detected_as_ambiguous(self):
        title = "Member of Technical Staff"
        description = (
            "Looking for an engineer to build deep learning models with PyTorch and computer vision, "
            "while managing our distributed system and Kafka streaming infrastructure, "
            "and developing full stack web applications with React and Node.js."
        )
        is_ambig, reason = is_job_description_ambiguous(title, description)
        self.assertTrue(is_ambig)
        self.assertIn("cross-disciplinary", reason.lower())

    def test_sparse_description_generic_title_detected_as_ambiguous(self):
        title = "Software Engineer"
        description = "Looking for smart programmers who love solving problems. Freshers welcome to apply."
        is_ambig, reason = is_job_description_ambiguous(title, description)
        self.assertTrue(is_ambig)
        self.assertIn("vague/sparse", reason.lower())

    def test_targeted_specialized_role_not_ambiguous(self):
        title = "React Frontend Developer"
        description = (
            "We are seeking a Frontend Engineer specializing strictly in React and TypeScript. "
            "You will build modern web user interfaces, optimize Redux state management, "
            "and ensure responsive styling with Tailwind CSS. Minimum 1 year frontend experience."
        )
        is_ambig, reason = is_job_description_ambiguous(title, description)
        self.assertFalse(is_ambig)


class ResumeNamingAndFolderTests(unittest.TestCase):
    def test_resume_naming_scheme(self):
        company = "Hewlett Packard Enterprise"
        title = "AI Engineer"
        import re, os
        clean_company = re.sub(r'_+', '_', "".join([c for c in company if c.isalnum() or c in (' ', '_')]).replace(' ', '_')).strip('_')
        clean_title = re.sub(r'_+', '_', "".join([c for c in title if c.isalnum() or c in (' ', '_')]).replace(' ', '_')).strip('_')
        
        expected_md = f"Madhav_Jayam_{clean_company}_{clean_title}_Resume.md"
        expected_pdf = f"Madhav_Jayam_{clean_company}_{clean_title}_Resume.pdf"
        
        self.assertEqual(expected_md, "Madhav_Jayam_Hewlett_Packard_Enterprise_AI_Engineer_Resume.md")
        self.assertEqual(expected_pdf, "Madhav_Jayam_Hewlett_Packard_Enterprise_AI_Engineer_Resume.pdf")
        self.assertEqual(clean_company, "Hewlett_Packard_Enterprise")

    def test_selected_projects_receive_verified_github_links(self):
        markdown = """## Selected Projects

### CareerTime (Python, LangChain)
- Built a career intelligence application.

### Unmatched Project (Python)
- Kept without an unverified URL.
"""
        portfolio = [{
            "name": "CareerTime",
            "display_name": "CareerTime: LPU-Accelerated AI Career Specialist",
            "full_name": "madhavofficial/CareerTime",
            "url": "https://github.com/madhavofficial/CareerTime",
        }]

        result = ensure_selected_project_github_links(markdown, portfolio)

        self.assertIn("*GitHub: https://github.com/madhavofficial/CareerTime*", result)
        self.assertEqual(result.count("https://github.com/madhavofficial/CareerTime"), 1)
        self.assertNotIn("Unmatched Project\n*GitHub:", result)

    def test_existing_project_link_is_not_duplicated(self):
        markdown = """## Selected Projects
### CareerTime
*GitHub: https://github.com/madhavofficial/CareerTime*
- Built a career intelligence application.
"""
        portfolio = [{"name": "CareerTime", "url": "https://github.com/madhavofficial/CareerTime"}]

        result = ensure_selected_project_github_links(markdown, portfolio)

        self.assertEqual(result.count("https://github.com/madhavofficial/CareerTime"), 1)

    def test_career_objective_names_target_company_and_position(self):
        markdown = """# Madhav Jayam

## Career Objective
Software engineering student seeking an internship.

## Education
PES University
"""
        result = ensure_career_objective_target(markdown, "Acme AI", "Backend Engineer Intern")

        self.assertIn("**Backend Engineer Intern**", result)
        self.assertIn("**Acme AI**", result)

    def test_career_objective_target_is_not_duplicated(self):
        markdown = """# Madhav Jayam
## Career Objective
Targeting the **Backend Engineer Intern** position at **Acme AI**.
"""
        result = ensure_career_objective_target(markdown, "Acme AI", "Backend Engineer Intern")

        self.assertEqual(result.count("Backend Engineer Intern"), 1)

    def test_bold_career_objective_heading_is_updated_in_place(self):
        markdown = """# Madhav Jayam
## **CAREER OBJECTIVE**
Seeking a software engineering role.

## **Education**
PES University
"""
        result = ensure_career_objective_target(markdown, "GE HealthCare", "Software Engineering Intern")

        self.assertEqual(result.count("Career Objective"), 0)
        self.assertIn("**Software Engineering Intern**", result)
        self.assertIn("**GE HealthCare**", result)
        self.assertEqual(result.count("## **CAREER OBJECTIVE**"), 1)

    def test_career_objective_contains_employment_ready_punch(self):
        markdown = """# Madhav Jayam

## Career Objective
Aspiring Computer Science student with experience in software engineering.

## Education
PES University
"""
        result = ensure_career_objective_target(markdown, "Stripe", "Software Engineer")
        self.assertIn("Employment-ready", result)
        self.assertIn("**Software Engineer**", result)
        self.assertIn("**Stripe**", result)
        self.assertIn("resilient, production-grade software", result)


    def test_enforce_one_page_budget_returns_valid_string(self):
        from tailor import enforce_one_page_budget
        sample_md = """# Candidate Name\n## Education\nPES University\n## Professional Experience\n### Qualcomm\n- Bullet 1\n- Bullet 2\n- Bullet 3\n- Bullet 4\n"""
        result = enforce_one_page_budget(sample_md, profile_id="madhav", strict_mode=False)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, str)
        self.assertIn("Qualcomm", result)

    def test_ensure_education_retains_markdown(self):
        from tailor import ensure_education
        sample_md = """# Candidate Name\n## Professional Experience\n### Test Corp\n- Work bullet\n"""
        result = ensure_education(sample_md)
        self.assertIsNotNone(result)
        self.assertIn("Education", result)
        self.assertIn("PES University", result)

    def test_scrub_unverified_metrics_removes_hardware_and_fpga_fabrication(self):
        from tailor import scrub_unverified_metrics
        sample_md = """# Candidate Name
## Career Objective
Computer Science undergraduate at PES University with a solid grounding in electronic circuits, digital/analogue design and embedded systems. Seeking a hardware engineering internship at Tejas Networks to contribute to high-speed board and FPGA development while expanding hands-on experience in telecom-grade hardware R&D.

## Technical Skills
- **Embedded / Hardware:** ROS 2, Arduino, FUSE, Linux, OpenCV, VHDL/Verilog (academic exposure), digital/analogue circuit fundamentals
- **Languages:** Python, Java, C
"""
        cleaned = scrub_unverified_metrics(sample_md, profile_id="mahika")
        self.assertNotIn("electronic circuits", cleaned.lower())
        self.assertNotIn("digital/analogue", cleaned.lower())
        self.assertNotIn("fpga development", cleaned.lower())
        self.assertNotIn("hardware engineering internship", cleaned.lower())
        self.assertNotIn("telecom-grade hardware r&d", cleaned.lower())
        self.assertNotIn("vhdl/verilog", cleaned.lower())
        self.assertIn("low-level c programming", cleaned.lower())
        self.assertIn("operating-system internals", cleaned.lower())
        self.assertIn("embedded software engineering internship", cleaned.lower())
        self.assertIn("embedded & systems software", cleaned.lower())

    def test_anti_clustering_and_flagship_rule_for_mahika(self):
        from profiles import MAHIKA_PROFILE
        # Verify topics on neuro_capstone include full-stack and database
        topics = MAHIKA_PROFILE.curated_projects["neuro_capstone"]["topics"]
        self.assertIn("full-stack", topics)
        self.assertIn("database", topics)
        self.assertIn("postgresql", topics)

        # Verify flagship instruction contains anti-clustering and flagship principles
        flagship_inst = MAHIKA_PROFILE.flagship_instruction
        self.assertIn("ANTI-CLUSTERING RULE", flagship_inst)
        self.assertIn("CORE FLAGSHIP PRINCIPLE", flagship_inst)
        self.assertIn("NEVER select both 'Enterprise Loan Management System' and 'Personal Wealth Management Application'", flagship_inst)

    def test_madhav_literature_synthesis_anti_duplication(self):
        from profiles import MADHAV_PROFILE
        flagship_inst = MADHAV_PROFILE.flagship_instruction
        self.assertIn("CRITICAL ANTI-DUPLICATION RULE", flagship_inst)
        self.assertIn("NEVER list 'Multi-Agent Generative AI System for Scientific Literature Analysis' under '## Selected Projects'", flagship_inst)

        from tailor import scrub_unverified_metrics
        sample_md = """# Madhav Jayam
## Selected Projects
### GLAS-Med: Evidence-Grounded Clinical Literature Synthesis
- Multi-agent micro-service ingesting 300-800 papers.

### Multi-Modal AI Protein Analysis & Pathogenicity Reasoning Platform
- Clinical AI platform.

### Multi-Agent Generative AI System for Scientific Literature Analysis
- Autonomous system retrieving biomedical literature.

## Publications
- **Conference Acceptance**: Selected for **IEEE SPICES**
"""
        cleaned = scrub_unverified_metrics(sample_md, profile_id="madhav")
        # Check that scientific literature was scrubbed from Selected Projects
        selected_proj_part = cleaned.split("## Publications")[0]
        self.assertNotIn("Scientific Literature Analysis", selected_proj_part)
        self.assertIn("GLAS-Med", selected_proj_part)
        self.assertIn("Multi-Modal AI Protein Analysis", selected_proj_part)
        # Check that Publications is preserved
        self.assertIn("IEEE SPICES", cleaned)

    def test_strip_meta_commentary(self):
        sample_md = """# Madhav Jayam
## Technical Skills
- **Languages**: Python, C++

--

*This resume is formatted to fit a single page when compiled with LaTeX.*
Note: Target exactly 1 page budget.
"""
        cleaned = strip_meta_commentary(sample_md)
        self.assertNotIn("formatted to fit a single page", cleaned)
        self.assertNotIn("compiled with LaTeX", cleaned)
        self.assertNotIn("1 page budget", cleaned)
        self.assertIn("Languages", cleaned)


if __name__ == "__main__":
    unittest.main()


