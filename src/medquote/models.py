from pydantic import BaseModel, Field
from typing import Optional


class QuoteLineItem(BaseModel):
    """A single line item from a medical equipment quote, normalized
    into the target Excel template columns.

    Per data_model.md: fields that are not universally present across
    vendor templates are Optional. Only description is guaranteed.
    """

    catalog_number: Optional[str] = Field(
        default=None,
        description="Catalog # / Equipment # / SKU / Part Number from the quote. "
        "Not all items have one (e.g. shipping, training). "
        "Leave blank if no identifier of any kind is present.",
    )
    description: str = Field(
        description="Item name or description of the equipment/service. "
        "This is the only universally present field across all vendor quotes."
    )
    component: Optional[str] = Field(
        default=None,
        description="Sub-component or line-item breakdown level. "
        "If the quote has grouped/nested items, this is the specific component. "
        "Leave blank if it's a standalone line item.",
    )
    quantity: Optional[int] = Field(
        default=None,
        description="Quantity ordered (QTY). Check dedicated quantity column "
        "first, then look for implied quantities in the description "
        "(e.g. 'x2', 'qty 3'). Only default to 1 if no quantity "
        "indication exists anywhere in the line item.",
    )
    list_price: Optional[float] = Field(
        default=None,
        description="List price or MSRP per unit. "
        "If not explicitly shown, leave null — do not infer or fabricate.",
    )
    net_price: Optional[float] = Field(
        default=None,
        description="Net/unit price — the actual selling price per unit. "
        "If only one price column exists, use that as net_price. "
        "If ambiguous between per-unit and total, flag instead of splitting.",
    )
    ext_list_price: Optional[float] = Field(
        default=None,
        description="Extended list price = list_price × quantity. "
        "If explicitly stated on the quote, use that value. "
        "Otherwise calculate it if both list_price and quantity are known.",
    )
    ext_net_price: Optional[float] = Field(
        default=None,
        description="Extended net price = net_price × quantity. "
        "If explicitly stated on the quote, use that value. "
        "Otherwise calculate it if both net_price and quantity are known.",
    )
    discount: Optional[str] = Field(
        default=None,
        description="Discount percentage or amount if explicitly shown. "
        "E.g. '15%' or '$500.00'. Can also be calculated as "
        "(list_price - net_price) / list_price if both are known. "
        "Leave blank if unclear.",
    )
    additional_info: Optional[str] = Field(
        default=None,
        description="Any additional information from the quote about this item. "
        "Also use this field to FLAG nomenclature uncertainties — "
        "e.g. 'Uncertain: this appears to be a service contract but is listed "
        "under equipment', or 'Per-unit vs total price ambiguous — "
        "single price covers multiple items'.",
    )


class QuoteDocument(BaseModel):
    """Represents everything extracted from a single quote PDF.

    Per data_model.md: source_id, quote_number, and quote_date are
    expected to be present on nearly all quotes but the model should
    leave them null (not fabricate) if genuinely absent.
    """

    source_id: str = Field(
        description="Manufacturer name or vendor name, followed by ' Quote'. "
        "E.g. 'GE HealthCare Quote', 'Hillrom Quote', 'Bracco Diagnostics Quote'"
    )
    quote_number: str = Field(
        description="Quote or reference number from the document"
    )
    quote_date: str = Field(
        description="Date the quote was issued, as written on the document"
    )
    title: str = Field(
        description="Full title for the output: "
        "Source ID + Quote # + Date. "
        "E.g. 'GE HealthCare Quote #1-72V2HP59 - 05/08/2025'"
    )
    line_items: list[QuoteLineItem] = Field(
        description="All line items from this quote. "
        "Parse EVERY item listed on the quote — do not skip any. "
        "For multi-page quotes with summary sections and detail sections, "
        "prefer the detailed line-item breakdown."
    )
