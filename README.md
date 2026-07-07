# medquote-extractor

Phase 1 of the Medical Equipment Quote Extraction & Review System build order.

This is a throwaway script that proves the core loop:
PDF -> raw text -> 5 hardcoded fields via structured LLM output.

No database, no UI, no validation logic, no sidecar confidence object.
Those arrive in later phases per the locked architecture plan.

## Setup

1. `pip install -e .`
2. Copy `.env.example` to `.env` and add your `OPENAI_API_KEY`.
3. Drop 2-3 sample quote PDFs into `sample_quotes/`.
4. Run `python main.py`.

## Scope (Phase 1 only)

- Ingestion: extract raw text from PDF using pdfplumber.
- Extraction: call OpenAI structured output (Pydantic response_format) for exactly 5 fields.
- Output: print parsed fields to console. Nothing is persisted.

## Explicitly out of scope for this phase

- Supabase / quotes_draft / quotes_approved tables
- Confidence sidecar object
- Structural validation (date parsing, math reconciliation)
- Review UI
- OCR fallback for scanned documents
