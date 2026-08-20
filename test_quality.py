import os
import tempfile
import unittest

from pdf_utils import markdown_to_pdf


class QualityOfLifeTests(unittest.TestCase):
    def test_pdf_renderer_writes_pdf(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = os.path.join(temp_dir, "resume.pdf")
            markdown_to_pdf("# Madhav Jayam\n\n## Education\n- PES University\n\n## Experience\nBackend engineering", output)
            self.assertTrue(os.path.isfile(output))
            with open(output, "rb") as stream:
                self.assertEqual(stream.read(5), b"%PDF-")

    def test_pdf_text_normalizes_ats_unsafe_unicode(self):
        from pdf_utils import _plain_markdown
        rendered = _plain_markdown("Backend — AI-powered ‘platform’")
        self.assertEqual(rendered, "Backend - AI-powered &#x27;platform&#x27;")


if __name__ == "__main__":
    unittest.main()
