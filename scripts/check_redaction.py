#!/usr/bin/env python3
"""Run all sample PDFs through redaction and report key metrics."""
from medquote.ingestion import extract_text, extract_text_from_scanned_pdf
from medquote.redaction import redact_customer_info
import re
import os

SAMPLES_DIR = "/tmp/medquote-extractor/sample_quotes"
PDFS = [
    "GE Quote.pdf",
    "Hillrom Quote.pdf",
    "Zeiss Quote (2).pdf",
    "Bracco Diagnostics Quote.pdf",
]


def count_occurrences(text: str, *targets: str) -> int:
    """Count total occurrences of target strings."""
    total = 0
    for t in targets:
        total += len(re.findall(re.escape(t), text, re.IGNORECASE))
    return total


for pdf_name in PDFS:
    pdf_path = os.path.join(SAMPLES_DIR, pdf_name)
    if not os.path.exists(pdf_path):
        print(f"\n{'='*60}")
        print(f"SKIPPED: {pdf_name} — file not found")
        continue

    print(f"\n{'='*60}")
    print(f"FILE: {pdf_name}")
    print(f"{'='*60}")

    raw_text = extract_text(pdf_path)
    if not raw_text.strip():
        raw_text = extract_text_from_scanned_pdf(pdf_path)
        print(f"  (scanned PDF — text from OCR)")

    print(f"  Raw length: {len(raw_text)} chars")

    # Count key entities before
    person_before = count_occurrences(raw_text, "Bracco")
    zeiss_before = count_occurrences(raw_text, "Zeiss", "Carl Zeiss")
    kern_before = count_occurrences(raw_text, "KERN")
    catalog_before = len(re.findall(r"\b\d{4,10}-\d{2,4}(?:-\d{2,4})?\b", raw_text))

    redacted = redact_customer_info(raw_text)

    # Count key entities after
    person_after = count_occurrences(redacted, "Bracco", "Carl Zeiss Meditec USA", "Carl Zeiss")
    kern_after = count_occurrences(redacted, "KERN")
    catalog_after = len(re.findall(r"\b\d{4,10}-\d{2,4}(?:-\d{2,4})?\b", redacted))
    phone_after = count_occurrences(redacted, "<PHONE_NUMBER>")
    email_after = count_occurrences(redacted, "<EMAIL_ADDRESS>")
    location_after = count_occurrences(redacted, "<LOCATION>")
    person_token_after = count_occurrences(redacted, "<PERSON>")
    redacted_facility_after = count_occurrences(redacted, "[REDACTED FACILITY]")

    print(f"\n  ── Key Entity Changes ──")
    print(f"  Bracco/Zeiss (vendor names):  {person_before} → {person_after}")
    print(f"  KERN (facility name):          {kern_before} → {kern_after}")
    print(f"  Catalog numbers:               {catalog_before} → {catalog_after}")
    print(f"\n  ── Surviving Redaction Tokens ──")
    print(f"  <PERSON> tokens:               {person_token_after}")
    print(f"  <PHONE_NUMBER> tokens:         {phone_after}")
    print(f"  <EMAIL_ADDRESS> tokens:        {email_after}")
    print(f"  <LOCATION> tokens:             {location_after}")
    print(f"  [REDACTED FACILITY] instances: {redacted_facility_after}")

    # Show a sample of what survived
    lines = redacted.split('\n')
    lines_with_person = [l for l in lines if '<PERSON>' in l or '[REDACTED FACILITY]' in l]
    if lines_with_person:
        print(f"\n  ── Lines with redaction tokens (sample, max 5) ──")
        for l in lines_with_person[:5]:
            print(f"    > {l.strip()[:120]}")

print("\n\nDone.")
