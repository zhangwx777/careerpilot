import io
import unittest

from docx import Document
from pypdf import PdfWriter

from app.resume_extract import ResumeExtractError, extract_resume


class ResumeExtractTestCase(unittest.TestCase):
    def test_extracts_docx_text(self):
        document = Document()
        document.add_paragraph("Python 后端工程师")
        output = io.BytesIO()
        document.save(output)
        self.assertEqual(extract_resume("resume.docx", output.getvalue()), "Python 后端工程师")

    def test_rejects_unsupported_file(self):
        with self.assertRaisesRegex(ResumeExtractError, "只支持"):
            extract_resume("resume.txt", b"resume")

    def test_rejects_textless_pdf(self):
        output = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.write(output)
        with self.assertRaisesRegex(ResumeExtractError, "没有提取到"):
            extract_resume("resume.pdf", output.getvalue())


if __name__ == "__main__":
    unittest.main()
