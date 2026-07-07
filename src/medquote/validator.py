"""Lightweight post-processing validation for extracted quote data.

This module runs AFTER AI extraction but BEFORE Excel export.
It performs deterministic fixes that don't need another LLM call:
- Vendor name canonicalization
- Discount calculation
- Extended price validation
- Flagging obvious issues
"""

from medquote.models import QuoteDocument, QuoteLineItem

# Canonical vendor name mappings: any key found in source_id
# will be replaced with the canonical value.
# Order matters — check more specific matches first.
_VENDOR_CANONICAL = {
    "cz meditec": "Carl Zeiss Meditec USA, Inc.",
    "carl zeiss meditec usa": "Carl Zeiss Meditec USA, Inc.",
    "zeiss": "Carl Zeiss Meditec USA, Inc.",
    "ge healthcare": "GE HealthCare",
    "ge": "GE HealthCare",
    "hillrom": "Hillrom",
    "hill-rom": "Hillrom",
    "bracco diagnostics": "Bracco Diagnostics Inc",
    "bracco": "Bracco Diagnostics Inc",
}


def _canonicalize_vendor(raw_source_id: str) -> str:
    """Normalize vendor names to canonical forms.

    Strips ' Quote' suffix, matches against known aliases,
    then re-appends ' Quote'.
    """
    base = raw_source_id
    if base.lower().endswith(" quote"):
        base = base[: -len(" Quote")]

    lower = base.lower().strip()
    for alias, canonical in _VENDOR_CANONICAL.items():
        if alias in lower:
            return f"{canonical} Quote"

    return raw_source_id


def _compute_discount(item: QuoteLineItem) -> str | None:
    """Calculate discount percentage if list and net prices are known."""
    if item.list_price and item.net_price and item.list_price > 0:
        discount_pct = (item.list_price - item.net_price) / item.list_price
        if discount_pct > 0:
            return f"{discount_pct:.1%}"
    return item.discount


def _flag_price_anomalies(item: QuoteLineItem) -> str | None:
    """Check for obvious price issues and return a flag string."""
    issues = []
    if item.list_price and item.net_price and item.net_price > item.list_price:
        issues.append("Net price exceeds list price")
    if item.ext_list_price and item.list_price and item.quantity:
        expected_ext_list = item.list_price * item.quantity
        if abs(item.ext_list_price - expected_ext_list) > 0.02 * expected_ext_list:
            issues.append(f"Ext. list price ({item.ext_list_price}) ≠ list×qty ({expected_ext_list:.2f})")
    if item.ext_net_price and item.net_price and item.quantity:
        expected_ext_net = item.net_price * item.quantity
        if abs(item.ext_net_price - expected_ext_net) > 0.02 * expected_ext_net:
            issues.append(f"Ext. net price ({item.ext_net_price}) ≠ net×qty ({expected_ext_net:.2f})")
    if issues:
        existing = item.additional_info or ""
        flag = "; ".join(issues)
        return f"{existing} ⚠ {flag}" if existing else f"⚠ {flag}"
    return item.additional_info


def _calculate_extended_prices(item: QuoteLineItem) -> QuoteLineItem:
    """Fill in extended prices where unit prices and qty are known but ext is not."""
    if item.ext_list_price is None and item.list_price is not None and item.quantity:
        item.ext_list_price = round(item.list_price * item.quantity, 2)
    if item.ext_net_price is None and item.net_price is not None and item.quantity:
        item.ext_net_price = round(item.net_price * item.quantity, 2)
    return item


def validate_quote(doc: QuoteDocument) -> QuoteDocument:
    """Run all validation/normalization on a single QuoteDocument."""
    # Step 1: Canonicalize vendor name
    doc.source_id = _canonicalize_vendor(doc.source_id)
    doc.title = f"{doc.source_id} #{doc.quote_number} - {doc.quote_date}"

    # Step 2: Normalize each line item
    for item in doc.line_items:
        item = _calculate_extended_prices(item)
        item.discount = _compute_discount(item)
        item.additional_info = _flag_price_anomalies(item)

    return doc
