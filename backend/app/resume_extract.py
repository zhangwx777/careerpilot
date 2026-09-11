from io import BytesIO
from pathlib import PurePath


class ResumeExtractError(ValueError):
    pass


MAX_RESUME_BYTES = 10 * 1024 * 1024
SUPPORTED_SUFFIXES = {".pdf", ".docx"}


def extract_resume(filename: str | None, content: bytes) -> str:
    suffix = PurePath(filename or "").suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ResumeExtractError("简历只支持 PDF 或 DOCX 文件")
    if len(content) > MAX_RESUME_BYTES:
        raise ResumeExtractError("简历文件不能超过 10 MB")
    if suffix == ".pdf":
        from pypdf import PdfReader

        text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(content)).pages)
    else:
        from docx import Document

        document = Document(BytesIO(content))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    text = text.strip()
    if not text:
        raise ResumeExtractError("没有提取到简历文字，请上传可复制文字的 PDF 或 DOCX")
    return text
