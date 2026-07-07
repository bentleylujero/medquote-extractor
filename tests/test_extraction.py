import glob
import os
import pytest
from medquote.ingestion import extract_text
from medquote.extraction import extract_fields

SAMPLE_DIR = "sample_quotes"


@pytest.mark.skipif(
    not glob.glob(os.path.join(SAMPLE_DIR, "*.pdf")),
    reason="No sample PDFs available in sample_quotes/",
)
def test_smoke_extraction_on_first_sample():
    path = glob.glob(os.path.join(SAMPLE_DIR, "*.pdf"))[0]
    text = extract_text(path)
    assert text.strip() != "", "Expected a real text layer for this smoke test"

    result = extract_fields(text)

    assert result.vendor.strip() != ""
    assert result.quote_number.strip() != ""
    assert result.quote_date.strip() != ""
    assert result.total_amount is not None
    assert result.item_description.strip() != ""
