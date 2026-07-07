# Data Model — medquote-extractor

This document defines the data model, extraction rules, and export semantics
for medical equipment quote extraction. The code in `src/medquote/models.py`,
`extraction.py`, and `exporter.py` implements these definitions — this file is
the authoritative source of truth.

---

## Line Item Classification

Every line item on a quote MUST be classified into exactly one of the following
8 `ComponentCategory` enum values. Never invent new categories — if uncertain,
choose the closest match.

| Component Category  | Description |
|---------------------|-------------|
| Base                | The main/primary item being quoted, usually the first line item, often identified by a "model" label or system name. This is the core equipment. |
| Hardware Options    | Hardware add-ons, optional hardware features, or peripheral hardware. |
| Software Options    | Software add-ons, licenses, or optional software features. |
| Upgrades            | Upgrades to existing equipment already owned by the customer. |
| Accessories         | Consumables, add-on peripherals, or small accessories. |
| Training            | On-site or remote training services. |
| Installation        | Installation, setup, or commissioning services. |
| Freight             | Shipping, freight, delivery, or transport charges. |

Trade-in Allowance and Discount are NOT component categories — they are
separate fields on the line item (see below).

---

## Base System Null-Pricing Rule

The Base system must always be included as its own line item, classified as
`Base`, even if the quote does not display a separate price for it.

**Crucial**: When the Base system's cost is distributed across itemized
components rather than priced separately, the Base line item's price fields
(list_price, net_price, ext_list_price, ext_net_price) MUST be left as null —
do NOT set them to 0.

- `null` means "price not separately stated in the source document"
- `0` means "priced at zero," which is a materially different statement

Null-priced line items are excluded from proportional discount calculations
in Sheet B (see below). They are not treated as $0.

---

## Trade-In Allowance

If the quote explicitly states a trade-in allowance for a specific line item,
extract it as `trade_in_allowance` with a **negative** value (representing a
credit/reduction).

Trade-in allowances are typically labeled:
- "Trade-in"
- "Trade Allowance"
- "Less: Trade"

Never infer or fabricate a trade-in value. If no trade-in is mentioned, leave
the field as null.

---

## Discount Line Item Detection

A quote may have an explicit standalone discount as its own row in the
document. This is distinct from discounts already reflected within each line
item's net price (which is the common case and remains unchanged).

**Characteristics of a discount line item:**
- Appears as a separate row in the quote's table
- Has a negative or discount amount (e.g. `-$5,000.00`)
- Has a description like "Discount", "Less: Discount", "Contract Discount",
  "Negotiated Discount", etc.

**Detection flag:** `has_discount_line_item` is set to `True` on the
`QuoteDocument` only when such an explicit standalone discount row exists.

When the discount is embedded in per-line net prices (the common case):
- `has_discount_line_item = False`
- Existing logic in `validator.py` handles per-line discount calculation
- No dual-sheet export is triggered

---

## Conditional Dual-Sheet Export

When `has_discount_line_item = True`, the exporter generates **two sheets**
for that quote:

### Sheet A — "Discount as Line Item"
All line items as extracted from the document, including the standalone
discount line item with its negative value. A summary row shows the total of
all line items (which should equal the quote's stated grand total).

### Sheet B — "Discount Applied Proportionally"
The discount amount is spread across all priced line items proportionally
by their list price.

**Calculation rules:**
1. Exclude the discount line item from the set of items to price.
2. Exclude any line item with null/blank pricing (unpriced Base, etc.).
   Do not treat null-priced items as $0.
3. Let `list_total` = sum of `ext_list_price` across all priced line items.
4. Let `total_discount_amount` = the absolute value of the discount line item.
5. Compute `x = total_discount_amount / list_total`
6. For every remaining priced line item, compute:
   `ext_net_price = ext_list_price × (1 − x)`

A note row explains the calculation (discount amount, number of priced items,
applied percentage).

Quotes **without** `has_discount_line_item` continue to export as a single
sheet with no structural changes — the per-line net prices already reflect
any applicable discounts.

---

## Extraction Rules (Summary)

1. **Manufacturer Identification**: Extract only the OEM of the base unit.
   Ignore resellers, distributors, and contact names.

2. **Field Truthfulness**: Leave blank rather than fabricating missing values.

3. **Skip Optional Items**: Do not extract optional or alternate configurations.

4. **Implied Quantities**: Check item descriptions for quantity indicators
   (x2, qty 3, etc.). Default to 1 only if no indication exists.

5. **Catalog Number Flexibility**: Extract whatever identifier is present
   (catalog#, part#, SKU, item#). Leave blank if none.

6. **Vendor Name Normalization**: Prefer the full legal name from the
   letterhead or signature block. Append " Quote" for source_id.

7. **Ambiguous Pricing**: Flag in additional_info rather than splitting
   aggregate totals into fabricated per-unit prices.
