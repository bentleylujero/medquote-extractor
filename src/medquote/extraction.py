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
    "VENDOR NAME NORMALIZATION (CRITICAL):\n"
    "- For source_id, always extract the vendor's FULL LEGAL NAME as it appears "
    "most completely in the document. Prefer the version in the letterhead, "
    "signature block, or top-level company name over abbreviated references.\n"
    "- Example: if the document says 'CZ Meditec (USA)' in a header but "
    "'Carl Zeiss Meditec USA, Inc.' in the body, use 'Carl Zeiss Meditec USA, Inc.'\n"
    "- Example: 'GE' in a logo area but 'GE HealthCare' on the invoice — use "
    "'GE HealthCare'\n"
    "- Example: 'Hillrom' vs 'Hill-Rom' vs 'Hillrom, Inc.' — use the most "
    "complete version you see in the document body.\n"
    "- Then append ' Quote' to form source_id. E.g. 'Carl Zeiss Meditec USA, Inc. Quote'\n\n"
    "KEY RULES:\n"
    "1. Parse ALL line items — every row in every table on every page. "
    "Do not skip anything.\n"
    "2. Handle weird nomenclature: medical equipment vendors use inconsistent "
    "naming. Use your best judgment to map whatever the vendor wrote into the "
    "correct schema field.\n"
    "3. For nested/grouped items (e.g. a system with sub-components), create "
    "separate line items for each sub-component AND note the grouping in "
    "component/additional_info.\n"
    "4. source_id should be the MANUFACTURER'S FULL LEGAL NAME followed by ' Quote'. "
    "E.g. 'GE HealthCare Quote', 'Hillrom Quote', 'Carl Zeiss Meditec USA, Inc. Quote'.\n"
    "5. title should be: source_id + ' #' + quote_number + ' - ' + quote_date. "
    "E.g. 'GE HealthCare Quote #1-72V2HP59 - 05/08/2025'.\n"
    "6. Use the additional_info field to FLAG anything you're uncertain about — "
    "weird descriptions, ambiguous catalog numbers, unclear discounts, "
    "or items that seem miscategorized.\n"
    "7. For ext_list_price and ext_net_price: if the quote explicitly shows "
    "the extended total, use that value. If not, calculate: price × qty.\n"
    "8. For discount: if not explicitly shown but both list and net prices "
    "are known, calculate the discount percentage.\n"
    "9. If a field cannot be found or inferred, make your best reasonable "
    "inference from context — do NOT invent data that contradicts the document. "
    "Leave null if genuinely not present.\n"
    "10. Include service/maintenance/shipping line items too — not just equipment."
)


def extract_quote(text: str, model: str = "gpt-4o-2024-08-06") -> QuoteDocument:
    """Extract full quote data using structured output."""
    response = _client.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        response_format=QuoteDocument,
    )
    return response.choices[0].message.parsed
