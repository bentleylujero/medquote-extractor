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
import time
from openai import OpenAI, RateLimitError, APIError
from dotenv import load_dotenv
from medquote.models import QuoteDocument
import tiktoken

load_dotenv()

_DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-2024-08-06")

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
    "=== COMPONENT CLASSIFICATION ===\n\n"
    "Every line item MUST be classified into exactly one ComponentCategory "
    "enum value. The 8 valid values are:\n"
    "  - Base: The main/primary item being quoted, usually the first line "
    "item, often identified by a 'model' label or system name. This is the "
    "core equipment.\n"
    "  - Hardware Options: Hardware add-ons, optional hardware features, "
    "or peripheral hardware.\n"
    "  - Software Options: Software add-ons, licenses, or optional software "
    "features.\n"
    "  - Upgrades: Upgrades to existing equipment already owned by the "
    "customer.\n"
    "  - Accessories: Consumables, add-on peripherals, or small accessories.\n"
    "  - Training: On-site or remote training services.\n"
    "  - Installation: Installation, setup, or commissioning services.\n"
    "  - Freight: Shipping, freight, delivery, or transport charges.\n\n"
    "Never invent new categories. If uncertain, choose the closest match. "
    "Trade-in Allowance and Discount are NOT component categories — they are "
    "separate fields on the line item.\n\n"
    "=== BASE SYSTEM HANDLING ===\n\n"
    "Always identify and include the base/primary system as its own line item, "
    "classified as 'Base'. The Base system must be present even if it has no "
    "listed price on the quote.\n\n"
    "Important: When the Base system's cost is distributed across itemized "
    "components rather than priced separately, the Base line item's price "
    "fields (list_price, net_price, ext_list_price, ext_net_price) should be "
    "left NULL — do NOT set them to 0. Null means 'price not separately "
    "stated'; 0 means 'priced at zero', which is different.\n\n"
    "CRITICAL: Do NOT attach the quote's subtotal/grand-total figure to the "
    "Base line item. The Base line item should only carry a price if the "
    "document explicitly lists a unit price or extended price for that "
    "specific catalog item. Summary rows at the bottom of the quote "
    "(Subtotal, List Total, Total, Grand Total) are NOT the Base item's "
    "price — ignore them for line-item pricing.\n\n"
    "HIERARCHICAL/GROUPED ITEMS: Some quotes use a grouped-item format where "
    "a parent item (e.g. 'Item 1: System Name') has no price of its own but "
    "lists sub-components underneath it (like 01SYSFRS, 10TUBMFO, etc.). "
    "In this format: extract ONLY the sub-components as individual line items. "
    "Do NOT also extract the group/parent item as a separate line item — "
    "that would double-count the system. The group/parent is just a header "
    "for the sub-items. Give the first priced sub-component the 'Base' "
    "component category. Never extract both a parent and its child as "
    "separate line items.\n\n"
    "=== DISCOUNT LINE ITEM DETECTION ===\n\n"
    "Determine whether the quote contains an explicit standalone discount "
    "as its own line item. A discount line item is characterized by:\n"
    "  - It appears as a separate row in the quote's table\n"
    "  - It has a negative or discount amount (e.g. '-$5,000.00' or "
    "'Discount - 5,000.00')\n"
    "  - It has a description like 'Discount', 'Less: Discount', "
    "'Contract Discount', 'Negotiated Discount', etc.\n\n"
    "Set has_discount_line_item = True on QuoteDocument only if such an "
    "explicit standalone discount row exists. If discounts are already "
    "reflected in the per-line net prices (which is the common case), "
    "set has_discount_line_item = False.\n\n"
    "When has_discount_line_item is True, the discount line item MUST be "
    "included as a line item in line_items. Make it a regular QuoteLineItem "
    "with description like 'Discount', 'Order Discount', etc., a negative "
    "ext_net_price (and negative net_price if a unit price is shown), "
    "component = null (the discount itself is not equipment), and flag it "
    "in additional_info as 'Standalone discount line item'.\n\n"
    "=== TRADE-IN ALLOWANCE ===\n\n"
    "If the quote explicitly states a trade-in allowance for a specific "
    "line item, extract it as trade_in_allowance with a negative value. "
    "Trade-in allowances are typically labeled 'Trade-in', 'Trade Allowance', "
    "'Less: Trade', etc. Never infer or fabricate a trade-in value. "
    "If no trade-in is mentioned, leave the field as null.\n\n"
    "=== ADDITIONAL FORMATTING RULES ===\n\n"
    "8. title format: source_id + ' #' + quote_number + ' - ' + quote_date. "
    "E.g. 'GE HealthCare Quote #1-72V2HP59 - 05/08/2025'.\n"
    "9. Parse ALL line items — every row in every table on every page. "
    "Do not skip anything.\n"
    "10. Use the additional_info field to FLAG anything you're uncertain "
    "about — weird descriptions, ambiguous catalog numbers, unclear discounts, "
    "or items that seem miscategorized.\n"
    "11. For service, maintenance, shipping, and training line items: include "
    "them as line items with component = Training, Installation, or Freight "
    "as applicable.\n"
    "12. For ext_list_price and ext_net_price: if the quote explicitly shows "
    "the extended total, use that value. If not, calculate: price × qty.\n"
    "13. For discount: if not explicitly shown but both list and net prices "
    "are known, calculate the discount percentage.\n"
    "14. For nested/grouped items (e.g. a system with sub-components), create "
    "separate line items for each sub-component AND note the grouping in "
    "additional_info.\n"
    "15. DOCUMENT TOTAL VERIFICATION: Many quotes include a subtotal, "
    "list-total, or grand-total figure near the bottom (e.g. 'Subtotal 699,538.14', "
    "'List Total 726,907.85', 'Total 757,142.79'). "
    "FIRST: Extract this figure into the 'document_subtotal' field on "
    "QuoteDocument (the field exists specifically for this purpose). "
    "SECOND: After extracting ALL line items, sum their ext_net_price values "
    "(including negative discount items). If your sum does NOT match the "
    "document's stated subtotal (within $1.00), you have likely MISSED one or "
    "more line items. Go back and check the document again for items you "
    "missed — especially Freight, Shipping, Accessories, Training, "
    "Installation, or small-dollar items near the end of the quote. "
    "The document's stated subtotal is the correct total. If you cannot "
    "find the missing item(s), flag the discrepancy in the last line "
    "item's additional_info field as 'Total mismatch: sum=XXX vs document=YYY'.\n"
)


_TOKEN_LIMIT = 100_000

def _check_token_limit(text: str, model: str) -> int:
    """Return token count and warn if near the limit."""
    try:
        enc = tiktoken.encoding_for_model(model)
    except KeyError:
        enc = tiktoken.get_encoding("cl100k_base")
    token_count = len(enc.encode(text))
    if token_count > _TOKEN_LIMIT:
        raise ValueError(
            f"Input text is {token_count:,} tokens, which exceeds the safe limit "
            f"of {_TOKEN_LIMIT:,}. Consider splitting the document."
        )
    return token_count


def extract_quote(text: str, model: str = _DEFAULT_MODEL, retries: int = 3) -> QuoteDocument:
    """Extract full quote data using structured output.

    Args:
        text: Raw text extracted from the PDF (via pdfplumber or OCR).
        model: OpenAI model supporting response_format structured output.
        retries: Number of retry attempts on transient API errors.

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
    - Classify every line item into 8-value ComponentCategory enum
    - Include Base system even if unpriced (null, not 0)
    - Detect standalone discount line items for dual-sheet export
    - Extract trade-in allowance separately when explicitly stated
    """
    token_count = _check_token_limit(text, model)
    print(f"  Token estimate: {token_count:,}")
    for attempt in range(retries):
        try:
            response = _client.chat.completions.parse(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": text},
],
                response_format=QuoteDocument,
            )
            return response.choices[0].message.parsed
        except RateLimitError:
            if attempt < retries - 1:
                wait = 2 ** attempt
                print(f"  Rate limited. Retrying in {wait}s... (attempt {attempt + 1}/{retries})")
                time.sleep(wait)
            else:
                raise
        except APIError as exc:
            if attempt < retries - 1:
                print(f"  API error: {exc}. Retrying... (attempt {attempt + 1}/{retries})")
                time.sleep(2)
            else:
                raise
