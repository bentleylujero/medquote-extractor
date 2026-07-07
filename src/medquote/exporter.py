import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side, numbers
from medquote.models import QuoteDocument, QuoteLineItem

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

# Style constants
HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
TITLE_FILL = PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid")
TITLE_FONT = Font(bold=True, size=12, color="1F4E79")
FLAG_FILL = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")  # light yellow
THIN_BORDER = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)


def _write_title_row(ws, row: int, doc: QuoteDocument, max_col: int) -> int:
    """Write the quote title across the top with a shaded background."""
    title_text = f"{doc.title}"
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=max_col)
    cell = ws.cell(row=row, column=1, value=title_text)
    cell.font = TITLE_FONT
    cell.fill = TITLE_FILL
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


def _write_line_item(ws, row: int, item: QuoteLineItem):
    """Write a single line item row.

    Price values are stored as actual numbers (not formatted strings)
    so Excel can sum/filter them. The NumberFormat handles display.
    """
    # Price columns: store as actual numbers with $ format
    list_price = item.list_price if item.list_price is not None else None
    net_price = item.net_price if item.net_price is not None else None
    ext_list = item.ext_list_price if item.ext_list_price is not None else None
    ext_net = item.ext_net_price if item.ext_net_price is not None else None

    values = [
        item.catalog_number,          # 1 - Catalog #
        item.description,             # 2 - Description
        item.component or "",         # 3 - Component
        item.quantity,                # 4 - QTY (number)
        list_price,                   # 5 - List Price (number or None)
        net_price,                    # 6 - Net Price (number or None)
        ext_list,                     # 7 - Ext. List Price (number or None)
        ext_net,                      # 8 - Ext. Net Price (number or None)
        item.discount or "",          # 9 - Discount (string like "12.5%")
        item.additional_info or "",   # 10 - Additional Information
    ]

    has_flags = bool(item.additional_info)

    for col_idx, val in enumerate(values, start=1):
        cell = ws.cell(row=row, column=col_idx, value=val)
        cell.border = THIN_BORDER

        # Price columns: right-align, dollar format, actual numbers
        if col_idx in (5, 6, 7, 8):
            cell.alignment = Alignment(horizontal="right", vertical="top")
            if val is not None:
                cell.number_format = '$#,##0.00'
        elif col_idx == 9 and val:
            # Discount is a text string like "12.5%"
            cell.alignment = Alignment(horizontal="right", vertical="top")
        elif col_idx == 10:
            # Additional Info: wrap text for readability
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        else:
            cell.alignment = Alignment(vertical="top")

        # Highlight rows with flags in yellow
        if has_flags:
            cell.fill = FLAG_FILL

    return row + 1


def _auto_width(ws, max_col: int, max_row: int):
    """Automatically adjust column widths based on content.

    Sets sensible minimums and maximums per column type.
    """
    # Prescribed minimum widths per column (by 1-index)
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
        col_letter = openpyxl.utils.get_column_letter(col_idx)
        for row in range(1, max_row + 1):
            cell = ws.cell(row=row, column=col_idx)
            if cell.value is not None:
                # Rough width: characters, up to 2x for price strings
                cell_len = len(str(cell.value))
                if cell_len > max_len:
                    max_len = cell_len

        # Apply minimum
        adjusted = max(max_len + 3, min_widths.get(col_idx, 12))
        # Apply maximum cap
        cap = max_widths.get(col_idx, 50)
        adjusted = min(adjusted, cap)

        ws.column_dimensions[col_letter].width = adjusted


def export_to_excel(docs: list[QuoteDocument], output_path: str):
    """Write all extracted quotes into a single Excel workbook.

    Each quote gets its own block: title (shaded) → header → line items.
    Rows with flags in additional_info are highlighted yellow.
    Price columns store actual numbers with $ format for filtering/summing.

    Args:
        docs: List of QuoteDocument objects from extraction + validation.
        output_path: Path for the .xlsx output file.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Quote Line Items"

    max_col = len(HEADERS)
    current_row = 1

    for doc_idx, doc in enumerate(docs):
        if doc_idx > 0:
            # Blank separator row between quotes
            current_row += 1

        # Title row (merged across all columns, shaded background)
        current_row = _write_title_row(ws, current_row, doc, max_col)

        # Header row
        current_row = _write_header_row(ws, current_row)

        # Line items
        if not doc.line_items:
            cell = ws.cell(row=current_row, column=1, value="No line items extracted")
            cell.alignment = Alignment(horizontal="center")
            ws.merge_cells(
                start_row=current_row,
                start_column=1,
                end_row=current_row,
                end_column=max_col,
            )
            current_row += 1
        else:
            for item in doc.line_items:
                current_row = _write_line_item(ws, current_row, item)

    # Auto-adjust column widths
    _auto_width(ws, max_col, current_row - 1)

    # Freeze below the first quote's header
    ws.freeze_panes = "A2"

    wb.save(output_path)
