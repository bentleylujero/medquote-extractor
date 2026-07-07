import os
import glob
from medquote.ingestion import extract_text
from medquote.extraction import extract_quote

SAMPLE_DIR = "sample_quotes"


def main():
    pdf_paths = glob.glob(os.path.join(SAMPLE_DIR, "*.pdf"))
    if not pdf_paths:
        print(f"No PDFs found in {SAMPLE_DIR}/. Add sample quotes and rerun.")
        return

    for path in pdf_paths:
        print(f"\n--- {os.path.basename(path)} ---")
        text = extract_text(path)
        if not text.strip():
            print("WARNING: no text layer detected (likely scanned/image-only). "
                  "Skipping LLM call -- this document would default to 'needs review' in Phase 3.")
            continue

        result = extract_quote(text)
        print(result.model_dump())


if __name__ == "__main__":
    main()
