"""PDF to a list of pages with text and 1-based page numbers."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from docai.schema import Document, Page


def parse_pdf(path: str | Path) -> Document:
    path = Path(path)
    reader = PdfReader(path)
    pages = [Page(number=i + 1, text=page.extract_text() or "") for i, page in enumerate(reader.pages)]
    return Document(doc_id=path.stem, pages=pages)


def render_for_prompt(doc: Document) -> str:
    return "\n\n".join(f"=== PAGE {p.number} ===\n{p.text.strip()}" for p in doc.pages)
