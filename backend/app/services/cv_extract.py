from __future__ import annotations

from io import BytesIO

from docx import Document
from pypdf import PdfReader


def extract_text_from_upload(filename: str, content: bytes) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return _extract_pdf(content)
    if lower.endswith(".docx"):
        return _extract_docx(content)
    raise ValueError("unsupported file type; use .pdf or .docx")


def _extract_pdf(content: bytes) -> str:
    reader = PdfReader(BytesIO(content))
    chunks: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            chunks.append(text.strip())
    return "\n".join(chunks).strip()


def _extract_docx(content: bytes) -> str:
    doc = Document(BytesIO(content))
    chunks = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
    return "\n".join(chunks).strip()
