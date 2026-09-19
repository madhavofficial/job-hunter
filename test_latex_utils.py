import os
import unittest
import latex_utils


class LatexUtilsTests(unittest.TestCase):
    def test_clean_glyphs(self):
        text = "Test ‚Äî dash â†’ arrow â‰¥ gte"
        cleaned = latex_utils._clean_glyphs(text)
        self.assertIn("-", cleaned)
        self.assertIn("->", cleaned)
        self.assertIn(">=", cleaned)

    def test_escape_latex(self):
        text = "Cost is $100 & profit is 50% for user_name #1 {ok} ~test ^pow"
        escaped = latex_utils.escape_latex(text)
        self.assertIn(r"\$100", escaped)
        self.assertIn(r"\&", escaped)
        self.assertIn(r"50\%", escaped)
        self.assertIn(r"user\_name", escaped)
        self.assertIn(r"\#1", escaped)

    def test_format_inline_latex(self):
        text = "Built with **Python** and *FastAPI* alongside [GitHub](https://github.com/Mahika6) and `docker`."
        formatted = latex_utils.format_inline_latex(text)
        self.assertIn(r"\textbf{Python}", formatted)
        self.assertIn(r"\textit{FastAPI}", formatted)
        self.assertIn(r"\href{https://github.com/Mahika6}{\underline{GitHub}}", formatted)
        self.assertIn(r"\textbf{docker}", formatted)

    def test_markdown_to_latex_structure(self):
        sample_md = """# Mahika Neranjen
**Email**: mahika@example.com | **Phone**: +91-9108836868 | **LinkedIn**: [linkedin.com/in/mahika](https://linkedin.com)
**Location**: Bengaluru, Karnataka

---

## Career Objective
Targeting the Technology Analyst role.

## Technical Skills
- **Languages**: Python, Java, C, TypeScript
- **Frameworks**: React, FastAPI, Flask
"""
        tex = latex_utils.markdown_to_latex(sample_md)
        self.assertIn(r"\documentclass[letterpaper,10pt]{article}", tex)
        self.assertIn(r"\textbf{\Huge \scshape Mahika Neranjen}", tex)
        self.assertIn(r"\section{Career Objective}", tex)
        self.assertIn(r"\section{Technical Skills}", tex)
        self.assertIn(r"\textbf{Languages}", tex)
        self.assertIn(r"\end{document}", tex)

    def test_compile_latex_to_pdf_with_tectonic(self):
        sample_md = """# Test Candidate
**Email**: test@example.com | **Phone**: 123-456-7890

---

## Career Objective
Seeking software engineering role.

## Technical Skills
- **Languages**: Python, C++
"""
        tex = latex_utils.markdown_to_latex(sample_md)
        scratch_dir = "/Users/madhavjayam/.gemini/antigravity-cli/brain/ac14f0c0-cc95-4569-8285-d8e3915ae0c5/scratch"
        pdf_path = os.path.join(scratch_dir, "unit_test_resume.pdf")
        tex_path = os.path.join(scratch_dir, "unit_test_resume.tex")
        
        ok = latex_utils.compile_latex_to_pdf(tex, pdf_path, tex_path)
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(pdf_path))
        self.assertTrue(os.path.exists(tex_path))


if __name__ == "__main__":
    unittest.main()
