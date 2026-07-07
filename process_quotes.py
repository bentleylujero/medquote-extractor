#!/usr/bin/env python3
"""
medquote-extractor — Phase 2

Full pipeline:
  PDF(s) → extract text (pdfplumber + Google OCR fallback)
         → AI extracts ALL line items with nomenclature normalization
         → exports to Excel template

Usage:
  python process_quotes.py [--input-dir sample_quotes] [--output quotes_output.xlsx]

Environment:
  OPENAI_API_KEY              required
  GOOGLE_APPLICATION_CREDENTIALS  path to service account JSON key (for scanned PDFs)
"""

import os
import sys
import glob
import argparse
from medquote.ingestion import extract_text
from medquote.extraction import extract_quote
from medquote.validator import validate_quote
from medquote.exporter import export_to_excel


def main():
    parser = argparse.ArgumentParser(
        description="Extract line items from medical equipment quotes and export to Excel."
    )
    parser.add_argument(
        "--input-dir",
        default="sample_quotes",
        help="Directory containing PDF quote files (default: sample_quotes/)",
    )
    parser.add_argument(
        "--output",
        default="medquote_output.xlsx",
        help="Output Excel file path (default: medquote_output.xlsx)",
    )
    parser.add_argument(
        "--skip-ocr",
        action="store_true",
        help="Skip scanned PDFs instead of attempting OCR",
    )
    args = parser.parse_args()

    # Check for API key
    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not set. Create a .env file with your key.")
        sys.exit(1)

    # Check for Google credentials (warn but don't fail — text PDFs will still work)
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not cred_path or not os.path.exists(cred_path):
        print("NOTE: GOOGLE_APPLICATION_CREDENTIALS not set. Scanned PDFs will be skipped.")
        print("      Set it to your service account JSON key path for OCR support.\n")

    # Find PDFs
    pdf_paths = sorted(glob.glob(os.path.join(args.input_dir, "*.pdf")))
    if not pdf_paths:
        print(f"No PDFs found in {args.input_dir}/")
        sys.exit(1)

    print(f"Found {len(pdf_paths)} PDF(s) in {args.input_dir}/\n")

    docs = []
    for path in pdf_paths:
        basename = os.path.basename(path)
        print(f"{'='*60}")
        print(f"  Processing: {basename}")
        print(f"{'='*60}")

        # Step 1: Extract text (with OCR fallback unless --skip-ocr)
        text = extract_text(path, use_ocr_fallback=not args.skip_ocr)

        if not text.strip():
            print("  ⚠  No text extracted (scanned PDF and OCR unavailable/skipped).")
            print("     Skipping.\n")
            continue

        print(f"  Text length: {len(text)} chars (first 200 shown below)")
        print(f"  {text[:200].strip()}...\n")

        # Step 2: AI extraction
        print("  Calling AI for extraction...")
        try:
            doc = extract_quote(text)
            print(f"  ✓ Extracted: {doc.title}")
            print(f"    Raw line items: {len(doc.line_items)}")

            # Step 2b: Validation / normalization
            doc = validate_quote(doc, raw_text=text)
            print(f"  ✓ Validated: vendor normalized, prices computed, flags checked")
            print(f"    Final line items: {len(doc.line_items)}")
            for item in doc.line_items:
                flags = " ⚑" if item.additional_info else ""
                price_str = " (no price)"
                if item.ext_net_price is not None:
                    price_str = f" ${item.ext_net_price:,.2f}"
                elif item.net_price is not None:
                    price_str = f" ${item.net_price:,.2f} (unit)"
                cat = item.catalog_number or "(no cat #)"
                desc = (item.description or "")[:60]
                print(f"    - {cat} | {desc} |{price_str}{flags}")
            docs.append(doc)
        except Exception as exc:
            print(f"  ✗ Extraction failed: {exc}")

        print()

    if not docs:
        print("No quotes were successfully extracted. Nothing to export.")
        sys.exit(1)

    # Step 3: Export to Excel
    print(f"{'='*60}")
    print(f"  Exporting {len(docs)} quote(s) to {args.output}")
    print(f"{'='*60}")
    export_to_excel(docs, args.output)
    print(f"  ✓ Output written to: {os.path.abspath(args.output)}")

    # Summary
    total_items = sum(len(d.line_items) for d in docs)
    print(f"\nSummary: {len(docs)} quote(s), {total_items} line items exported.")


if __name__ == "__main__":
    main()
