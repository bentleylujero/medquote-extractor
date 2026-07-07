import os
from google.api_core.client_options import ClientOptions
from google.cloud import documentai

# Loaded once at module level
_client = None
_processor_name = None

_PROJECT_ID = "document-extract-501717"
_LOCATION = "us"  # us-central1 multi-region
_PROCESSOR_ID = "ef0450581192a2dc"


def _get_client():
    global _client, _processor_name
    if _client is None:
        cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if not cred_path or not os.path.exists(cred_path):
            raise RuntimeError(
                "GOOGLE_APPLICATION_CREDENTIALS not set or file not found. "
                "Set it to the path of your service account JSON key."
            )
        opts = ClientOptions(api_endpoint=f"{_LOCATION}-documentai.googleapis.com")
        _client = documentai.DocumentProcessorServiceClient(
            client_options=opts,
        )
        _processor_name = _client.processor_path(
            _PROJECT_ID, _LOCATION, _PROCESSOR_ID
        )
    return _client, _processor_name


def extract_text_from_scanned_pdf(path: str) -> str:
    """Send a scanned (image-only) PDF to Google Cloud Document AI OCR.

    Returns the full text extracted from all pages.
    Raises RuntimeError on API failures.
    """
    client, proc_name = _get_client()

    with open(path, "rb") as f:
        image_content = f.read()

    document = documentai.RawDocument(
        content=image_content,
        mime_type="application/pdf",
    )

    request = documentai.ProcessRequest(
        name=proc_name,
        raw_document=document,
    )

    result = client.process_document(request=request)

    # Concatenate text from all pages
    text_parts = []
    if result.document.text:
        text_parts.append(result.document.text)

    return "\n".join(text_parts)
