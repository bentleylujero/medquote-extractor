"""
Data models for medical equipment quote extraction.

The fields, enum values, and nullable rules here are documented in
data_model.md — that file is the source of truth for extraction semantics.
"""

from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class ComponentCategory(str, Enum):
    """Fixed 8-value enum for classifying every line item on a medical
    equipment quote.

    These categories are mutually exclusive per data_model.md. Every
    line item extracted MUST be assigned exactly one of these values.
    Never invent new categories.
    """
    BASE = "Base"
    HARDWARE_OPTIONS = "Hardware Options"
    SOFTWARE_OPTIONS = "Software Options"
    UPGRADES = "Upgrades"
    ACCESSORIES = "Accessories"
    TRAINING = "Training"
    INSTALLATION = "Installation"
    FREIGHT = "Freight"


class QuoteLineItem(BaseModel):
    """A single line item from a medical equipment quote, normalized
    into the target Excel template columns.

    Per data_model.md: fields that are not universally present across
    vendor templates are Optional. Only description is guaranteed.

    The ``component`` field uses the 8-value ComponentCategory enum
    defined in data_model.md. The base/primary system being quoted
    is classified as ``Base`` and may have null/blank pricing when its
    cost is distributed across itemized components rather than priced
    separately.
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
    component: Optional[ComponentCategory] = Field(
        default=None,
        description="Classification of the line item into one of the 8 "
        "fixed ComponentCategory enum values. Determined by the model "
        "based on context — never invent new categories. "
        "The base/primary system = Base. "
        "Hardware add-ons = Hardware Options. "
        "Software add-ons = Software Options. "
        "Upgrades to existing equipment = Upgrades. "
        "Consumables or add-on peripherals = Accessories. "
        "On-site or remote training = Training. "
        "Installation services = Installation. "
        "Shipping, freight, delivery = Freight.",
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
        "If not explicitly shown, leave null — do not infer or fabricate. "
        "For Base items whose cost is distributed across components, "
        "leave null rather than setting to 0.",
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
    trade_in_allowance: Optional[float] = Field(
        default=None,
        description="Trade-in allowance explicitly stated for this specific "
        "line item. Always negative (represents a credit/reduction). "
        "Only populate if the source document explicitly mentions a "
        "trade-in value for this item — never infer or fabricate.",
    )


class QuoteDocument(BaseModel):
    """Represents everything extracted from a single quote PDF.

    Per data_model.md: source_id, quote_number, and quote_date are
    expected to be present on nearly all quotes but the model should
    leave them null (not fabricate) if genuinely absent.

    ``has_discount_line_item`` indicates the quote contains an explicit
    standalone discount as its own line item (a negative-value row
    separate from per-line discounts embedded in net prices). When True,
    the exporter generates two sheets to show both raw and proportionally
    allocated views.
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
    has_discount_line_item: bool = Field(
        default=False,
        description="True when the quote contains an explicit standalone "
        "discount as its own line item (a negative-value row separate from "
        "discounts embedded per-line). False when per-line net prices "
        "already reflect any discounts. Triggers the dual-sheet export.",
    )
