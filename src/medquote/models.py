from pydantic import BaseModel, Field
from typing import Optional


class QuoteLineItem(BaseModel):
    """A single line item from a medical equipment quote, normalized
    into the target Excel template columns.
    """
    catalog_number: str = Field(
        description="Catalog # / Equipment # / SKU / Part Number from the quote"
    )
    description: str = Field(
        description="Item name or description of the equipment/service"
    )
    component: Optional[str] = Field(
        default=None,
        description="Sub-component or line-item breakdown level. "
        "If the quote has grouped/nested items, this is the specific component. "
        "Leave blank if it's a standalone line item."
    )
    quantity: int = Field(
        description="Quantity ordered (QTY). Default to 1 if not specified."
    )
    list_price: Optional[float] = Field(
        default=None,
        description="List price or MSRP per unit. "
        "If not explicitly shown, leave null and the AI can infer from context."
    )
    net_price: Optional[float] = Field(
        default=None,
        description="Net/unit price — the actual selling price per unit. "
        "If only one price column exists, use that as net_price."
    )
    ext_list_price: Optional[float] = Field(
        default=None,
        description="Extended list price = list_price × quantity. "
        "If explicitly stated on the quote, use that value. "
        "Otherwise calculate it if both list_price and quantity are known."
    )
    ext_net_price: Optional[float] = Field(
        default=None,
        description="Extended net price = net_price × quantity. "
        "If explicitly stated on the quote, use that value. "
        "Otherwise calculate it if both net_price and quantity are known."
    )
    discount: Optional[str] = Field(
        default=None,
        description="Discount percentage or amount if explicitly shown. "
        "E.g. '15%' or '$500.00'. Can also be calculated as "
        "(list_price - net_price) / list_price if both are known. "
        "Leave blank if unclear."
    )
    additional_info: Optional[str] = Field(
        default=None,
        description="Any additional information from the quote about this item. "
        "Also use this field to FLAG nomenclature uncertainties — "
        "e.g. 'Uncertain: this appears to be a service contract but is listed "
        "under equipment', or 'Description seems abbreviated, unclear mapping'."
    )


class QuoteDocument(BaseModel):
    """Represents everything extracted from a single quote PDF."""
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
