# medquote-extractor

End-to-end pipeline for extracting line items from medical equipment vendor PDF quotes and exporting them to a standardized Excel format.

## Status

**Phase 2 complete** — 4 text-based vendor quotes parsed (217 line items), Google Cloud Document AI OCR wired but needs billing enabled for scanned PDFs.

## Quick Start

```bash
# 1. Install
pip install -e .

# 2. Configure credentials
cp .env.example .env
# Edit .env with your OPENAI_API_KEY
# For scanned PDFs only: set GOOGLE_APPLICATION_CREDENTIALS=google-credentials.json

# 3. Drop PDFs into sample_quotes/
# 4. Run
python process_quotes.py
# Output: medquote_output.xlsx
```

## Pipeline

```
PDF -> text extraction (pdfplumber + OCR fallback) -> AI extraction (GPT-4o structured output) -> validation -> Excel export
```

## Architecture

| Module | Purpose |
|--------|---------|
| `process_quotes.py` | Entry point: orchestrates the full pipeline |
| `src/medquote/ingestion.py` | Text extraction from PDFs (pdfplumber + Google OCR fallback) |
| `src/medquote/ocr.py` | Google Cloud Document AI OCR for scanned documents |
| `src/medquote/extraction.py` | Schema-forced GPT-4o structured output |
| `src/medquote/models.py` | Pydantic schemas (QuoteDocument, QuoteLineItem) |
| `src/medquote/validator.py` | Post-processing: vendor canonicalization, price sanity, discount calc |
| `src/medquote/exporter.py` | Excel export with styled headers, auto-width, flag highlights |

## Excel Output Columns

| Column | Notes |
|--------|-------|
| Catalog # | Vendor SKU / part number |
| Description | Item description |
| Component | Sub-component or module name |
| QTY | Quantity |
| List Price | Stored as number, formatted as $#,##0.00 |
| Net Price | Stored as number, formatted as $#,##0.00 |
| Ext. List Price | Extended list price (QTY × List Price) |
| Ext. Net Price | Extended net price (QTY × Net Price) |
| Discount | Computed or extracted discount % |
| Additional Information | Flags for human review — highlighted in yellow |

## Challenges

- Medical equipment vendors use wildly inconsistent naming and catalog numbers
- Scanned PDFs require Google Cloud Document AI (billing must be enabled)
- Some line items are services, shipping, or training — not equipment — and must be flagged, not rejected

## Repository

Private — no vendor PDFs committed, no credentials in git history.
