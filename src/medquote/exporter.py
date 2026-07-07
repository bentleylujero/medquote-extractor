"""
Excel export module for medical equipment quote extraction.

Generates a single sheet for standard quotes, or two sheets when a quote
contains an explicit standalone discount line item:

  Sheet A ("Discount as Line Item"): Raw line items including the discount.
  Sheet B ("Discount Applied Proportionally"): Discount proportionally
    allocated across priced line items (excluding unpriced Base items).

The dual-sheet logic is documented in data_model.md.
"""

import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from medquote.models import QuoteDocument, QuoteLineItem
from typing import Optional

HEADERS = [
    "Catalog #",
    "Description",
    "Component",
    "QTY",
    "List Price",
    "Net Price",
    "Ext. List Price",
    "Ext. Net Price",
    "Discount",
    "Additional Information",
]

# ---------------------------------------------------------------------------
# Color tier definitions
# ---------------------------------------------------------------------------
# Each column is tagged with its data tier:
#   "green"  = taken verbatim from the quote document (rendered as white bg)
#   "yellow" = interpreted/derived from context in the quote
#   "red"    = N/A — any blank/null cell gets red fill
#
# The tier name determines the label shown on the section header row, and
# controls blank-cell fill colour.
# ---------------------------------------------------------------------------
COLUMN_TIERS = {
    1: "green",   # Catalog #
    2: "green",   # Description
    3: "yellow",  # Component (AI-classified)
    4: "green",   # QTY
    5: "green",   # List Price
    6: "green",   # Net Price
    7: "yellow",  # Ext. List Price (computed)
    8: "yellow",  # Ext. Net Price (computed)
    9: "yellow",  # Discount (derived)
   10: "yellow",  # Additional Information (AI flags)
}

# Style constants — no more yellow/orange fills on data rows
HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
TITLE_FONT = Font(bold=True, size=12, color="1F4E79")
SUBTOTAL_FILL = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
SUBTOTAL_FONT = Font(bold=True, size=11)

THIN_BORDER = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)

# Colour fills for data-tier indicators
GREEN_ACCENT = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
YELLOW_ACCENT = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
RED_ACCENT = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")

# Fill for blank/N/A cells
RED_FILL = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")


def _write_section_header(ws, row: int, doc: QuoteDocument, max_col: int) -> int:
    """Write a coloured data-tier label above the quote title.

    A single row with three coloured bands indicating which columns are
    green-tier (verbatim), yellow-tier (derived), and red-tier (N/A).
    """
    # Tier label: coloured bars above the quote
    tier_labels = {"green": "  Sourced  ", "yellow": " Derived ", "red": "   N/A   "}
    tier_colors = {"green": GREEN_ACCENT, "yellow": YELLOW_ACCENT, "red": RED_ACCENT}

    # Group contiguous columns by tier for merged label spans
    current_tier = None
    start_col = 1
    for col_idx in range(1, max_col + 1):
        col_tier = COLUMN_TIERS.get(col_idx, "red")
        if col_tier != current_tier:
            if current_tier is not None and start_col <= col_idx - 1:
                # Write the tier label
                label_cell = ws.cell(row=row, column=start_col, value=tier_labels[current_tier])
                label_cell.fill = tier_colors[current_tier]
                label_cell.font = Font(bold=True, size=9, color="555555")
                label_cell.alignment = Alignment(horizontal="center", vertical="center")
                label_cell.border = THIN_BORDER
                if col_idx - 1 > start_col:
                    ws.merge_cells(start_row=row, start_column=start_col, end_row=row, end_column=col_idx - 1)
            start_col = col_idx
            current_tier = col_tier
    # Write the last group
    if current_tier is not None:
        label_cell = ws.cell(row=row, column=start_col, value=tier_labels[current_tier])
        label_cell.fill = tier_colors[current_tier]
        label_cell.font = Font(bold=True, size=9, color="555555")
        label_cell.alignment = Alignment(horizontal="center", vertical="center")
        label_cell.border = THIN_BORDER
        if max_col > start_col:
            ws.merge_cells(start_row=row, start_column=start_col, end_row=row, end_column=max_col)

    return row + 1


def _write_title_row(ws, row: int, doc: QuoteDocument, max_col: int) -> int:
    """Write the quote title across the top — no coloured fill, just bold text."""
    title_text = f"{doc.title}"
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=max_col)
    cell = ws.cell(row=row, column=1, value=title_text)
    cell.font = TITLE_FONT
    cell.alignment = Alignment(horizontal="left", vertical="center")
    return row + 1


def _write_header_row(ws, row: int) -> int:
    """Write column headers with styled background."""
    for col_idx, header in enumerate(HEADERS, start=1):
        cell = ws.cell(row=row, column=col_idx, value=header)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = THIN_BORDER
    return row + 1


def _get_column_tier(col_idx: int) -> str:
    """Return the data tier for a column index: 'green', 'yellow', or 'red'."""
    return COLUMN_TIERS.get(col_idx, "red")


def _write_line_item(
    ws,
    row: int,
    item: QuoteLineItem,
    *,
    highlight_discount: bool = False,
) -> int:
    """Write a single line item row with colour-coded cells.

    Green-tier cells (sourced verbatim): white background.
    Yellow-tier cells (derived/interpreted): yellow fill.
    Any blank/null cell: red fill (N/A).
    """
    list_price = item.list_price if item.list_price is not None else None
    net_price = item.net_price if item.net_price is not None else None
    ext_list = item.ext_list_price if item.ext_list_price is not None else None
    ext_net = item.ext_net_price if item.ext_net_price is not None else None

    values = [
        item.catalog_number,                     # 1 - Catalog #
        item.description,                        # 2 - Description
        item.component.value if item.component else None,  # 3 - Component (None for N/A)
        item.quantity,                           # 4 - QTY (number)
        list_price,                              # 5 - List Price (number or None)
        net_price,                               # 6 - Net Price (number or None)
        ext_list,                                # 7 - Ext. List Price (number or None)
        ext_net,                                 # 8 - Ext. Net Price (number or None)
        item.discount,                           # 9 - Discount (string or None)
        item.additional_info,                    # 10 - Additional Information (string or None)
    ]

    for col_idx, val in enumerate(values, start=1):
        cell = ws.cell(row=row, column=col_idx, value=val)
        cell.border = THIN_BORDER
        tier = _get_column_tier(col_idx)

        # Apply colour based on tier and whether the cell is empty
        if val is None or (isinstance(val, str) and not val.strip()):
            # N/A → red fill
            cell.fill = RED_FILL
            # Keep the cell empty — don't write "N/A" text
            cell.value = None
        elif tier == "yellow":
            # Derived/interpreted value → yellow fill (with text in black)
            cell.fill = YELLOW_ACCENT
        else:
            # Green-tier (sourced verbatim) → white background (no fill)
            pass

        # Price columns: right-align, dollar format, actual numbers
        if col_idx in (5, 6, 7, 8):
            cell.alignment = Alignment(horizontal="right", vertical="top")
            if val is not None:
                cell.number_format = '$#,##0.00'
        elif col_idx == 9 and val:
            cell.alignment = Alignment(horizontal="right", vertical="top")
        elif col_idx == 10:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        else:
            cell.alignment = Alignment(vertical="top")

    return row + 1


def _write_summary_row(ws, row: int, label: str, value: Optional[float], max_col: int) -> int:
    """Write a summary row (e.g. subtotal, total) across columns."""
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=max_col - 1)
    label_cell = ws.cell(row=row, column=1, value=label)
    label_cell.font = SUBTOTAL_FONT
    label_cell.fill = SUBTOTAL_FILL
    label_cell.alignment = Alignment(horizontal="right", vertical="center")
    label_cell.border = THIN_BORDER

    value_cell = ws.cell(row=row, column=max_col, value=value)
    value_cell.font = SUBTOTAL_FONT
    value_cell.fill = SUBTOTAL_FILL
    value_cell.alignment = Alignment(horizontal="right", vertical="center")
    if value is not None:
        value_cell.number_format = '$#,##0.00'
    value_cell.border = THIN_BORDER

    # Fill merged cells with borders
    for c in range(2, max_col):
        cell = ws.cell(row=row, column=c)
        cell.fill = SUBTOTAL_FILL
        cell.border = THIN_BORDER

    return row + 1


def _auto_width(ws, max_col: int, max_row: int):
    """Automatically adjust column widths based on content."""
    min_widths = {
        1: 14,   # Catalog #
        2: 30,   # Description
        3: 16,   # Component
        4: 6,    # QTY
        5: 12,   # List Price
        6: 12,   # Net Price
        7: 14,   # Ext. List Price
        8: 14,   # Ext. Net Price
        9: 10,   # Discount
        10: 35,  # Additional Information
    }
    max_widths = {
        1: 24,
        2: 60,
        3: 30,
        10: 60,
    }

    for col_idx in range(1, max_col + 1):
        max_len = 0
        col_letter = get_column_letter(col_idx)
        for row in range(1, max_row + 1):
            cell = ws.cell(row=row, column=col_idx)
            if cell.value is not None:
                cell_len = len(str(cell.value))
                if cell_len > max_len:
                    max_len = cell_len

        adjusted = max(max_len + 3, min_widths.get(col_idx, 12))
        cap = max_widths.get(col_idx, 50)
        adjusted = min(adjusted, cap)

        ws.column_dimensions[col_letter].width = adjusted


def _build_line_item_rows(ws, doc: QuoteDocument, current_row: int, max_col: int) -> tuple[int, Optional[float]]:
    """Write line items for a quote and return (next_row, total_net).

    Returns the total ext_net_price for use in summary rows.
    """
    # Data-tier section header row (coloured bands)
    current_row = _write_section_header(ws, current_row, doc, max_col)
    # Title row
    current_row = _write_title_row(ws, current_row, doc, max_col)
    # Header row
    current_row = _write_header_row(ws, current_row)

    total_net = 0.0
    if not doc.line_items:
        cell = ws.cell(row=current_row, column=1, value="No line items extracted")
        cell.alignment = Alignment(horizontal="center")
        ws.merge_cells(
            start_row=current_row, start_column=1,
            end_row=current_row, end_column=max_col,
        )
        current_row += 1
    else:
        for item in doc.line_items:
            current_row = _write_line_item(ws, current_row, item)
            if item.ext_net_price is not None:
                total_net += item.ext_net_price

    return current_row, total_net


def _build_discount_as_line_item_sheet(wb, doc: QuoteDocument) -> str:
    """Sheet A: raw line items including the standalone discount line item."""
    ws = wb.create_sheet(title="Discount as Line Item")
    max_col = len(HEADERS)
    current_row, total_net = _build_line_item_rows(ws, doc, 1, max_col)

    # Summary row
    current_row = _write_summary_row(ws, current_row + 1, "Total (incl. discount)", total_net, max_col)

    # Auto-width and freeze
    _auto_width(ws, max_col, current_row - 1)
    ws.freeze_panes = "A2"

    return ws.title


def _build_proportional_allocation_sheet(wb, doc: QuoteDocument) -> str:
    """Sheet B: discount proportionally allocated across priced line items.

    Rules:
    1. Exclude the discount line item entirely.
    2. Exclude any line item with null/blank pricing (e.g. unpriced Base).
    3. Compute: x = total_discount_amount / list_total
       where list_total = sum of ext_list_price across priced items.
    4. For every remaining priced item: ext_net_price = ext_list_price * (1 - x).
    """
    # Separate line items: priced items vs discount line vs unpriced
    priced_items: list[QuoteLineItem] = []
    discount_items: list[QuoteLineItem] = []
    unpriced_items: list[QuoteLineItem] = []

    for item in doc.line_items:
        # An item is the discount line if it has a negative ext_net_price
        # or its description indicates discount
        is_negative = item.ext_net_price is not None and item.ext_net_price < 0
        is_discount_desc = item.description and "discount" in item.description.lower()
        if is_negative and is_discount_desc:
            discount_items.append(item)
        elif item.ext_list_price is not None and item.ext_net_price is not None:
            priced_items.append(item)
        else:
            unpriced_items.append(item)

    # Calculate total discount amount (positive value)
    total_discount = abs(sum(
        item.ext_net_price for item in discount_items if item.ext_net_price is not None
    )) if discount_items else 0.0

    # Calculate list total across priced items only
    list_total = sum(
        item.ext_list_price for item in priced_items if item.ext_list_price is not None
    ) if priced_items else 0.0

    # Calculate proportional allocation ratio
    x = total_discount / list_total if list_total > 0 else 0.0

    # Create the sheet
    ws = wb.create_sheet(title="Discount Applied Proportionally")
    max_col = len(HEADERS)

    # Data-tier section header
    current_row = _write_section_header(ws, 1, doc, max_col)
    # Title row
    current_row = _write_title_row(ws, current_row, doc, max_col)

    # Annotation row explaining the calculation — no fill, just italic text
    note = (
        f"Discount of ${total_discount:,.2f} allocated proportionally "
        f"at {x:.4%} across {len(priced_items)} priced line item(s)."
    )
    ws.merge_cells(
        start_row=current_row, start_column=1,
        end_row=current_row, end_column=max_col,
    )
    note_cell = ws.cell(row=current_row, column=1, value=note)
    note_cell.font = Font(italic=True, size=10, color="666666")
    note_cell.alignment = Alignment(horizontal="left", vertical="center")
    current_row += 1

    # Header row
    current_row = _write_header_row(ws, current_row)

    # List unpriced items first (shown for reference, no discount applied)
    for item in unpriced_items:
        current_row = _write_line_item(ws, current_row, item)
        # Override ext_net_price cell to show N/A (red)
        ext_net_cell = ws.cell(row=current_row - 1, column=8)
        ext_net_cell.value = None
        ext_net_cell.fill = RED_FILL
        ext_net_cell.number_format = '@'

    # Write priced items with proportionally adjusted ext_net_price
    total_adjusted_net = 0.0
    for item in priced_items:
        adjusted_ext_net = round(item.ext_list_price * (1 - x), 2) if item.ext_list_price is not None else None
        total_adjusted_net += adjusted_ext_net if adjusted_ext_net is not None else 0.0

        # Use normal _write_line_item, then override ext_net_price
        current_row = _write_line_item(ws, current_row, item)
        data_row = current_row - 1
        ext_net_cell = ws.cell(row=data_row, column=8)
        ext_net_cell.value = adjusted_ext_net
        if adjusted_ext_net is not None:
            ext_net_cell.number_format = '$#,##0.00'
            ext_net_cell.fill = YELLOW_ACCENT  # derived value

    # Summary row
    current_row = _write_summary_row(
        ws, current_row + 1,
        f"Total (after {x:.4%} proportional discount)",
        round(total_adjusted_net, 2),
        max_col,
    )

    _auto_width(ws, max_col, current_row - 1)
    ws.freeze_panes = "A2"

    return ws.title


def _build_single_sheet(wb, docs: list[QuoteDocument]) -> str:
    """Single-sheet export: all quotes in sequential blocks."""
    ws = wb.active
    ws.title = "Quote Line Items"

    max_col = len(HEADERS)
    current_row = 1

    for doc_idx, doc in enumerate(docs):
        if doc_idx > 0:
            current_row += 1  # blank separator

        current_row, _ = _build_line_item_rows(ws, doc, current_row, max_col)

    _auto_width(ws, max_col, current_row - 1)
    ws.freeze_panes = "A2"

    return ws.title


def export_to_excel(docs: list[QuoteDocument], output_path: str):
    """Write all extracted quotes into an Excel workbook.

    Standard behavior (no discount line items):
      Single sheet with all quotes in sequential blocks.

    With discount line items (any quote has has_discount_line_item=True):
      Two sheets per affected quote:
        Sheet A - "Discount as Line Item": raw data including the discount.
        Sheet B - "Discount Applied Proportionally": discount spread across
          priced items proportionally by list price.

    Quotes without discount line items remain single-sheet and are handled
    identically to the previous behavior.
    """
    wb = openpyxl.Workbook()

    # Check if any quote has a discount line item
    has_any_discount = any(doc.has_discount_line_item for doc in docs)

    if not has_any_discount:
        _build_single_sheet(wb, docs)
    else:
        default_ws = wb.active
        assert default_ws is not None

        sheets_created = []

        for doc in docs:
            if doc.has_discount_line_item:
                sheet_a = _build_discount_as_line_item_sheet(wb, doc)
                sheet_b = _build_proportional_allocation_sheet(wb, doc)
                sheets_created.extend([sheet_a, sheet_b])
            else:
                ws = wb.create_sheet(title=f"{doc.source_id[:20]}")
                max_col = len(HEADERS)
                _build_line_item_rows(ws, doc, 1, max_col)
                _auto_width(ws, max_col, ws.max_row)
                ws.freeze_panes = "A2"
                sheets_created.append(ws.title)

        if sheets_created:
            wb.remove(default_ws)

    wb.save(output_path)
