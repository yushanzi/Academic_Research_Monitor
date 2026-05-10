from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)

MAX_PDF_TEXT_CHARS = 50000
MAX_PDF_PAGES = 20


def extract_text_from_pdf_bytes(pdf_bytes: bytes, *, max_pages: int = MAX_PDF_PAGES, max_chars: int = MAX_PDF_TEXT_CHARS) -> str:
    if not pdf_bytes:
        return ""

    try:
        from pypdf import PdfReader
    except Exception as exc:  # pragma: no cover - dependency/import environment issue
        logger.warning("pypdf unavailable; cannot extract PDF text: %s", exc)
        return ""

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
    except Exception as exc:
        logger.debug("Failed to open PDF for text extraction: %s", exc)
        return ""

    extracted_parts: list[str] = []
    total_chars = 0
    for page in reader.pages[:max_pages]:
        try:
            page_text = page.extract_text() or ""
        except Exception as exc:
            logger.debug("Failed to extract text from PDF page: %s", exc)
            continue
        normalized = _normalize_pdf_text(page_text)
        if not normalized:
            continue
        remaining = max_chars - total_chars
        if remaining <= 0:
            break
        if len(normalized) > remaining:
            normalized = normalized[:remaining]
        extracted_parts.append(normalized)
        total_chars += len(normalized)
        if total_chars >= max_chars:
            break

    return _normalize_pdf_text("\n\n".join(extracted_parts))


def _normalize_pdf_text(text: str) -> str:
    return " ".join(text.split())
