import pdfplumber


def extract_text(path: str) -> str:
    """Extract raw text from a PDF's text layer.

    Phase 1 ingestion only: no OCR fallback, no scanned-document handling.
    If a document has no real text layer, this returns an empty string --
    that case is handled explicitly in Phase 3 validation ("needs review"),
    not here.
    """
    text_parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    return "\n".join(text_parts)
