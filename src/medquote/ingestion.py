import os
import pdfplumber

# On first import, check if Google OCR is available
_HAVE_OCR = False
try:
    from medquote.ocr import extract_text_from_scanned_pdf  # noqa: F401
    _HAVE_OCR = True
except Exception:
    pass


def extract_text(path: str, use_ocr_fallback: bool = True) -> str:
    """Extract raw text from a PDF's text layer.

    If the PDF has no text layer and use_ocr_fallback is True (default),
    falls back to Google Cloud Document AI OCR (requires GOOGLE_APPLICATION_CREDENTIALS).

    Returns the extracted text, or empty string if all methods fail.
    """
    text_parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    raw = "\n".join(text_parts)

    if raw.strip():
        return raw

    # Empty text layer — try OCR
    if use_ocr_fallback and _HAVE_OCR:
        try:
            from medquote.ocr import extract_text_from_scanned_pdf
            ocr_text = extract_text_from_scanned_pdf(path)
            if ocr_text.strip():
                return ocr_text
        except Exception as exc:
            print(f"  OCR fallback failed: {exc}")

    return raw  # still empty
