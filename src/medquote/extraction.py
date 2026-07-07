"""
Extraction module: structured quote extraction via OpenAI GPT-4o.

The extraction rules and data model semantics in this module derive from
the project's data_model.md. That document is the source of truth for
what fields are expected, which are optional vs required, and how the
model should handle ambiguity, missing data, and vendor-specific
nomenclature variability.

Before editing extraction rules or the system prompt, consult data_model.md
first — the schema semantics live there, not here.
"""

import os
from openai import OpenAI
from dotenv import load_dotenv
from medquote.models import QuoteDocument

load_dotenv()

_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

_SYSTEM_PROMPT = (
    "You extract structured medical equipment quote data from PDF text. "
    "Your job is to parse EVERY line item from the quote and normalize it into "
    "the target schema.\n\n"
    "=== CRITICAL EXTRACTION RULES (from data_model.md) ===\n\n"
    "1. MANUFACTURER IDENTIFICATION: "
    "Extract only the manufacturer of the base unit being quoted. "
    "Ignore resellers, distributors, and contact names or departments. "
    "The source_id must identify the original equipment manufacturer (OEM), "
    "not the intermediary who issued the quote.\n\n"
    "2. FIELD TRUTHFULNESS: "
    "If a field is not clearly present in the document text, leave it blank "
    "rather than guessing or inferring a value. Null/missing is always "
    "preferable to fabricated data.\n\n"
    "3. SKIP OPTIONAL ITEMS: "
    "Do not extract any line item labeled as optional, or any alternate or "
    "optional configuration of an item (e.g. 'with warranty' vs 'without'). "
    "Only extract the items that were actually ordered or quoted as the "
    "primary scope of supply.\n\n"
    "4. IMPLIED QUANTITIES: "
    "If quantity is not in a dedicated quantity field, check the item "
    "description for an implied quantity (e.g. 'x2', 'qty 3', '2 each', "
    "'qty.', '(2)') and extract it from there. Default to 1 only if no "
    "quantity indication exists anywhere in the line item.\n\n"
    "5. CATALOG NUMBER FLEXIBILITY: "
    "Product/catalog numbers may appear under different labels depending on "
    "vendor: equipment ID, product ID, item number, catalog number, part "
    "number, SKU, or simply 'item'. Extract whichever identifier is present "
    "as the catalog_number field, regardless of its label on the source "
    "document. If no identifier of any kind is present, leave blank.\n\n"
    "6. VENDOR NAME NORMALIZATION: "
    "Prefer the vendor's full legal name as shown in the letterhead or "
    "signature block over abbreviated references elsewhere in the document. "
    "E.g. if the header says 'CZ Meditec (USA)' but the signature block says "
    "'Carl Zeiss Meditec USA, Inc.', use the latter. Append ' Quote' to form "
    "source_id.\n\n"
    "7. AMBIGUOUS PRICING: "
    "If per-unit vs. total pricing is ambiguous (e.g. a single net price "
    "that covers multiple line items or multiple quantities), flag this in "
    "additional_info rather than attempting to split the price yourself. "
    "Do not invent per-unit prices from an aggregate total.\n\n"
    "=== ADDITIONAL FORMATTING RULES ===\n\n"
    "8. title format: source_id + ' #' + quote_number + ' - ' + quote_date. "
    "E.g. 'GE HealthCare Quote #1-72V2HP59 - 05/08/2025'.\n"
    "9. Parse ALL line items — every row in every table on every page. "
    "Do not skip anything.\n"
    "10. Use the additional_info field to FLAG anything you're uncertain "
    "about — weird descriptions, ambiguous catalog numbers, unclear discounts, "
    "or items that seem miscategorized.\n"
    "11. For service, maintenance, shipping, and training line items: include "
    "them as line items but flag in additional_info that they are not "
    "equipment.\n"
    "12. For ext_list_price and ext_net_price: if the quote explicitly shows "
    "the extended total, use that value. If not, calculate: price × qty.\n"
    "13. For discount: if not explicitly shown but both list and net prices "
    "are known, calculate the discount percentage.\n"
    "14. For nested/grouped items (e.g. a system with sub-components), create "
    "separate line items for each sub-component AND note the grouping in "
    "component/additional_info.\n"
)


def extract_quote(text: str, model: str = "gpt-4o-2024-08-06") -> QuoteDocument:
    """Extract full quote data using structured output.

    Args:
        text: Raw text extracted from the PDF (via pdfplumber or OCR).
        model: OpenAI model supporting response_format structured output.

    Returns:
        QuoteDocument with parsed fields per data_model.md rules.

    The extraction follows the rules defined in data_model.md:
    - Manufacturers only (no resellers/distributors)
    - No fabricated data for missing fields
    - No optional/alternate configurations
    - Implied quantities from descriptions
    - Flexible catalog number source
    - Full legal vendor name from letterhead/signature
    - Flag ambiguous pricing rather than splitting
    """
    response = _client.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        response_format=QuoteDocument,
    )
    return response.choices[0].message.parsed
