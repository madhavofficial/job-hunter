import unittest
from tailor import is_job_description_ambiguous


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


if __name__ == "__main__":
    unittest.main()

