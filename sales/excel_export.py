"""
Excel export for Proforma Invoices.

Produces a 2-sheet workbook that mirrors the client's template
("PI NO.32 FOR PAPER & SHEET"):

    Sheet "PI"     -> the client-facing Proforma Invoice (export format)
    Sheet "Sheet1" -> the internal Comparative Statement / Note Sheet
                      (vendor purchase cost + price break-up + approvals)

The PI sheet is built entirely from ProformaInvoice data. The Note Sheet
additionally pulls the *purchase* cost from the SELECTED vendor quotation
for each line (PI item -> requisition_item -> selected VendorQuotationItem),
converting the vendor's INR rate into the PI currency via conversion_rate.
Freight / export cost / last-supply comparison come from the new per-line
fields captured on the PI.
"""
from decimal import Decimal, InvalidOperation
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter


# ── Shared styles ───────────────────────────────────────────────────────────
THIN = Side(style='thin', color='000000')
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
BOLD = Font(bold=True, size=9)
BOLD_LG = Font(bold=True, size=12)
NORMAL = Font(size=9)
SMALL = Font(size=8)
HEAD_FILL = PatternFill('solid', fgColor='E5E7EB')
TITLE_FILL = PatternFill('solid', fgColor='F3F4F6')
CENTER = Alignment(horizontal='center', vertical='center', wrap_text=True)
LEFT = Alignment(horizontal='left', vertical='top', wrap_text=True)
RIGHT = Alignment(horizontal='right', vertical='center')


def _d(val):
    """Coerce anything to Decimal safely."""
    try:
        return Decimal(str(val or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal('0')


def _num(val):
    return float(_d(val))


def _fmt_date(d):
    if not d:
        return ''
    try:
        return d.strftime('%d.%m.%Y')
    except AttributeError:
        return str(d)


# ── Vendor purchase cost lookup ─────────────────────────────────────────────
def _purchase_rate_for_item(pi_item, pi_currency, conversion_rate):
    """
    Return (purchase_unit_price_in_pi_currency, vendor_offers).

    purchase_unit_price -> from the SELECTED vendor quotation for this line,
    converted from the quotation currency into the PI currency.
    vendor_offers -> [{'vendor': name, 'rate': Decimal(pi_currency), 'selected': bool}]
    """
    if not pi_item.requisition_item_id:
        return Decimal('0'), []

    # Imported lazily to avoid app-loading order issues.
    from requisitions.models import VendorQuotationItem

    vq_items = (
        VendorQuotationItem.objects
        .filter(vendor_item__requisition_item_id=pi_item.requisition_item_id)
        .select_related('quotation', 'quotation__assignment__vendor')
    )

    def to_pi_currency(rate, quote_currency):
        rate = _d(rate)
        # Vendor quoted in INR, PI in another currency -> divide by rate.
        if quote_currency == 'INR' and pi_currency != 'INR' and conversion_rate:
            cr = _d(conversion_rate)
            return rate / cr if cr else rate
        return rate

    offers = []
    selected_rate = Decimal('0')
    for vqi in vq_items:
        q = vqi.quotation
        rate = to_pi_currency(vqi.quoted_rate, q.currency)
        vendor_name = ''
        try:
            vendor_name = q.assignment.vendor.vendor_name
        except Exception:
            vendor_name = ''
        offers.append({'vendor': vendor_name, 'rate': rate, 'selected': q.is_selected})
        if q.is_selected:
            selected_rate = rate

    # If nothing explicitly selected, fall back to the cheapest offer.
    if selected_rate == 0 and offers:
        selected_rate = min(o['rate'] for o in offers)

    return selected_rate, offers


# ── Sheet builders ──────────────────────────────────────────────────────────
def _merge_consecutive(ws, row_values, column):
    """
    Vertically merge runs of consecutive rows that carry the same non-empty
    value in `column`. `row_values` is a list of (excel_row, value) in order.
    The merged cell keeps the top row's value, centred vertically.
    """
    mid_center = Alignment(horizontal='left', vertical='center', wrap_text=True)
    i = 0
    n = len(row_values)
    while i < n:
        row_i, val = row_values[i]
        j = i
        while val and j + 1 < n and (row_values[j + 1][1] == val):
            j += 1
        if j > i and val:
            ws.merge_cells(start_row=row_i, start_column=column,
                           end_row=row_values[j][0], end_column=column)
            ws.cell(row=row_i, column=column).alignment = mid_center
        i = j + 1


def _style_range(ws, cell_range, font=None, align=None, fill=None, border=True):
    for row in ws[cell_range]:
        for c in row:
            if font:
                c.font = font
            if align:
                c.alignment = align
            if fill:
                c.fill = fill
            if border:
                c.border = BORDER


def _build_pi_sheet(ws, pi, items, symbol):
    widths = [6, 16, 16, 12, 10, 8, 8, 10, 14, 14]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    last_col = 'G'

    r = 1
    ws.merge_cells(f'A{r}:{last_col}{r}')
    c = ws[f'A{r}']
    c.value = 'PROFORMA INVOICE'
    c.font = BOLD_LG
    c.alignment = CENTER
    c.fill = TITLE_FILL
    _style_range(ws, f'A{r}:{last_col}{r}')
    ws.row_dimensions[r].height = 22

    # ── Header info grid ────────────────────────────────────────────────
    def label_value(row, col_l, col_r, label, value, merge=True):
        if merge and col_l != col_r:
            ws.merge_cells(f'{col_l}{row}:{col_r}{row}')
        cell = ws[f'{col_l}{row}']
        cell.value = f'{label}\n{value}' if label else value
        cell.font = NORMAL
        cell.alignment = LEFT
        _style_range(ws, f'{col_l}{row}:{col_r}{row}')

    r += 1
    label_value(r, 'A', 'C', 'Exporter / Manufacturer:',
                pi.exporter_beneficiary or 'ENERGYPAC ENGINEERING LIMITED.')
    label_value(r, 'D', 'E', 'Proforma Invoice No. & Date:',
                f'{pi.pi_number}  DT. {_fmt_date(pi.pi_date)}')
    label_value(r, 'F', 'G', 'GST NO.:', pi.gst_number or '')
    ws.row_dimensions[r].height = 46

    r += 1
    label_value(r, 'A', 'C', 'Exporters Ref.:', pi.exporter_reference or '')
    label_value(r, 'D', 'E', 'L/C Number:', pi.lc_number or '')
    label_value(r, 'F', 'G', 'Currency:', pi.currency or '')

    r += 1
    label_value(r, 'A', 'C', 'Consignee:', pi.consignee or '')
    label_value(r, 'D', 'G', 'Applicant / Notify / Importer:', pi.applicant_importer or '')
    ws.row_dimensions[r].height = 40

    r += 1
    label_value(r, 'A', 'B', 'Pre-carriage by:', pi.pre_carriage_by or '')
    label_value(r, 'C', 'C', 'Place of Receipt:', pi.place_of_receipt or '')
    label_value(r, 'D', 'E', 'Country of Origin:', pi.country_of_origin or '')
    label_value(r, 'F', 'G', 'Final Destination:', pi.final_destination or '')
    ws.row_dimensions[r].height = 30

    r += 1
    label_value(r, 'A', 'C', 'Port of Loading:', pi.port_of_loading or '')
    label_value(r, 'D', 'G', 'Port of Discharge:', pi.port_of_discharge or '')

    r += 1
    label_value(r, 'A', 'C', 'Terms of Payment:', pi.terms_of_payment or '')
    label_value(r, 'D', 'G', 'Terms of Delivery:', pi.terms_of_delivery or '')
    ws.row_dimensions[r].height = 26

    # ── Items table ─────────────────────────────────────────────────────
    r += 1
    headers = ['SL #', 'Description of Goods', 'HS CODE NO', 'U.O.M', 'QTY',
               f'UNIT PRICE ({symbol})', f'TOTAL PRICE ({symbol})']
    for i, h in enumerate(headers, start=1):
        cell = ws.cell(row=r, column=i, value=h)
        cell.font = BOLD
        cell.alignment = CENTER
        cell.fill = HEAD_FILL
        cell.border = BORDER
    ws.row_dimensions[r].height = 26

    subtotal = Decimal('0')
    for idx, it in enumerate(items, start=1):
        r += 1
        desc = it.product.item_name if it.product_id else ''
        qty = _d(it.quantity)
        rate = _d(it.unit_price)
        amt = _d(it.amount) or (qty * rate)
        subtotal += amt
        row_vals = [
            idx, desc, it.hsn_code or '',
            it.unit or (it.product.unit if it.product_id else ''),
            _num(qty), _num(rate), _num(amt),
        ]
        for i, v in enumerate(row_vals, start=1):
            cell = ws.cell(row=r, column=i, value=v)
            cell.border = BORDER
            cell.font = NORMAL
            if i == 2:
                cell.alignment = LEFT
            elif i in (5, 6, 7):
                cell.alignment = RIGHT
                cell.number_format = '#,##0.00'
            else:
                cell.alignment = CENTER
        ws.row_dimensions[r].height = 30

    # Grand total
    r += 1
    ws.merge_cells(f'A{r}:F{r}')
    tc = ws[f'A{r}']
    tc.value = 'GRAND TOTAL'
    tc.font = BOLD
    tc.alignment = RIGHT
    tc.fill = HEAD_FILL
    grand = _d(pi.grand_total) or subtotal
    gc = ws.cell(row=r, column=7, value=_num(grand))
    gc.font = BOLD
    gc.number_format = '#,##0.00'
    gc.alignment = RIGHT
    gc.fill = HEAD_FILL
    _style_range(ws, f'A{r}:G{r}')

    # ── Terms & Conditions ──────────────────────────────────────────────
    r += 2
    ws.merge_cells(f'A{r}:G{r}')
    tc = ws[f'A{r}']
    tc.value = 'Terms & Conditions:'
    tc.font = BOLD
    tc.alignment = LEFT

    for term in (pi.terms_and_conditions or []):
        r += 1
        if isinstance(term, dict):
            text = f"{term.get('key') or term.get('label', '')}: {term.get('value', '')}"
        else:
            text = str(term)
        ws.merge_cells(f'A{r}:G{r}')
        cell = ws[f'A{r}']
        cell.value = text
        cell.font = SMALL
        cell.alignment = LEFT

    # ── Signature ───────────────────────────────────────────────────────
    r += 3
    ws.merge_cells(f'E{r}:G{r}')
    sc = ws[f'E{r}']
    sc.value = 'For Energypac Engineering Limited'
    sc.font = BOLD
    sc.alignment = CENTER
    r += 3
    ws.merge_cells(f'E{r}:G{r}')
    sc = ws[f'E{r}']
    sc.value = 'Authorized Signatory'
    sc.font = NORMAL
    sc.alignment = CENTER


def _build_note_sheet(ws, pi, items, symbol):
    widths = [6, 26, 8, 8, 13, 13, 13, 13, 16, 12, 13]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    conversion_rate = pi.conversion_rate
    pi_currency = pi.currency or 'INR'
    profit_pct = _d(pi.profit_loading_percent)

    r = 1
    ws.merge_cells(f'A{r}:K{r}')
    c = ws[f'A{r}']
    c.value = 'Comparative Statement / Note Sheet'
    c.font = BOLD_LG
    c.alignment = CENTER
    c.fill = TITLE_FILL

    r += 1
    ws.cell(row=r, column=1, value='PI NO:-').font = BOLD
    ws.merge_cells(f'B{r}:D{r}')
    ws.cell(row=r, column=2, value=f'{pi.pi_number}  DT. {_fmt_date(pi.pi_date)}').font = NORMAL
    r += 1
    ws.cell(row=r, column=1, value='Project Name:').font = BOLD
    ws.merge_cells(f'B{r}:D{r}')
    ws.cell(row=r, column=2, value=pi.project_name or '').font = NORMAL
    r += 1
    ws.cell(row=r, column=1, value='EXCHANGE RATE:').font = BOLD
    ws.cell(row=r, column=3, value=_num(conversion_rate)).font = NORMAL
    ws.cell(row=r, column=4, value=f'PER {pi_currency}').font = NORMAL

    # ── Section 1: Comparative statement ────────────────────────────────
    r += 2
    hdr_row = r
    headers = [
        'Sl. No.', 'Description', 'U.O.M', 'QTY',
        f'Unit Price\n(Ex. works)\n{symbol}', f'Total Price\n(Ex. works)\n{symbol}',
        f'Unit Price\n(CPT)\n{symbol}', f'Total Price\n(CPT)\n{symbol}',
        'LC No & Date', 'Last Unit Price', f'Last Total\n(CPT)\n{symbol}',
    ]
    for i, h in enumerate(headers, start=1):
        cell = ws.cell(row=r, column=i, value=h)
        cell.font = BOLD
        cell.alignment = CENTER
        cell.fill = HEAD_FILL
        cell.border = BORDER
    ws.row_dimensions[r].height = 42

    tot_exworks = Decimal('0')
    tot_cpt = Decimal('0')
    # Pre-compute purchase rates once (reused by section 2).
    computed = []
    for it in items:
        p_rate, offers = _purchase_rate_for_item(it, pi_currency, conversion_rate)
        computed.append((it, p_rate, offers))

    lc_rows = []  # (excel_row, lc_reference) -> used to merge shared LC cells
    for idx, (it, p_rate, offers) in enumerate(computed, start=1):
        r += 1
        lc_rows.append((r, (it.last_lc_reference or '').strip()))
        qty = _d(it.quantity)
        sale_unit = _d(it.unit_price)
        ex_total = qty * p_rate
        cpt_total = _d(it.amount) or (qty * sale_unit)
        last_up = _d(it.last_unit_price)
        tot_exworks += ex_total
        tot_cpt += cpt_total
        vals = [
            idx,
            it.product.item_name if it.product_id else '',
            it.unit or (it.product.unit if it.product_id else ''),
            _num(qty), _num(p_rate), _num(ex_total),
            _num(sale_unit), _num(cpt_total),
            it.last_lc_reference or '', _num(last_up), _num(last_up * qty),
        ]
        for i, v in enumerate(vals, start=1):
            cell = ws.cell(row=r, column=i, value=v)
            cell.border = BORDER
            cell.font = NORMAL
            if i == 2 or i == 9:
                cell.alignment = LEFT
            elif i in (4, 5, 6, 7, 8, 10, 11):
                cell.alignment = RIGHT
                cell.number_format = '#,##0.00'
            else:
                cell.alignment = CENTER
        ws.row_dimensions[r].height = 34

    # Merge consecutive rows that share the same (non-empty) LC No & Date into
    # one "common" cell, matching the client's hand-made comparative statement.
    _merge_consecutive(ws, lc_rows, column=9)

    r += 1
    ws.merge_cells(f'A{r}:D{r}')
    ws.cell(row=r, column=1, value='Total Amount').font = BOLD
    ws[f'A{r}'].alignment = RIGHT
    ws.cell(row=r, column=6, value=_num(tot_exworks)).number_format = '#,##0.00'
    ws.cell(row=r, column=8, value=_num(tot_cpt)).number_format = '#,##0.00'
    _style_range(ws, f'A{r}:K{r}')
    for col in (6, 8):
        ws.cell(row=r, column=col).font = BOLD
        ws.cell(row=r, column=col).alignment = RIGHT

    # ── Section 2: Price break-up ───────────────────────────────────────
    r += 3
    ws.merge_cells(f'A{r}:D{r}')
    c = ws[f'A{r}']
    c.value = 'PROFORMA INVOICE NO:-  price breakup based on selected offer:'
    c.font = BOLD
    ws.merge_cells(f'E{r}:F{r}')
    ws.cell(row=r, column=5, value=f'{pi.pi_number}  DT. {_fmt_date(pi.pi_date)}').font = NORMAL

    r += 1
    headers2 = [
        'Sl. No.', 'Description', 'U.O.M', 'QTY',
        f'Purchase Unit Price\n(Ex. works)\n{symbol}', f'Total Purchase\n(Ex. works)\n{symbol}',
        'Freight', 'Export Cost', f'Profit Loading\n@ {_num(profit_pct):g}%',
        f'Total Amount\n(CPT)\n{symbol}',
    ]
    for i, h in enumerate(headers2, start=1):
        cell = ws.cell(row=r, column=i, value=h)
        cell.font = BOLD
        cell.alignment = CENTER
        cell.fill = HEAD_FILL
        cell.border = BORDER
    ws.row_dimensions[r].height = 42

    t_purchase = t_freight = t_export = t_profit = t_cpt2 = Decimal('0')
    for idx, (it, p_rate, offers) in enumerate(computed, start=1):
        r += 1
        qty = _d(it.quantity)
        purchase_total = qty * p_rate
        freight = _d(it.freight)
        export_cost = _d(it.export_cost)
        profit = (purchase_total * profit_pct / 100) if profit_pct else Decimal('0')
        cpt = purchase_total + freight + export_cost + profit
        t_purchase += purchase_total
        t_freight += freight
        t_export += export_cost
        t_profit += profit
        t_cpt2 += cpt
        vals = [
            idx,
            it.product.item_name if it.product_id else '',
            it.unit or (it.product.unit if it.product_id else ''),
            _num(qty), _num(p_rate), _num(purchase_total),
            _num(freight), _num(export_cost), _num(profit), _num(cpt),
        ]
        for i, v in enumerate(vals, start=1):
            cell = ws.cell(row=r, column=i, value=v)
            cell.border = BORDER
            cell.font = NORMAL
            if i == 2:
                cell.alignment = LEFT
            elif i in (4, 5, 6, 7, 8, 9, 10):
                cell.alignment = RIGHT
                cell.number_format = '#,##0.00'
            else:
                cell.alignment = CENTER
        ws.row_dimensions[r].height = 34

    r += 1
    ws.merge_cells(f'A{r}:D{r}')
    ws.cell(row=r, column=1, value='Total Amount').font = BOLD
    ws[f'A{r}'].alignment = RIGHT
    for col, val in ((6, t_purchase), (7, t_freight), (8, t_export), (9, t_profit), (10, t_cpt2)):
        cell = ws.cell(row=r, column=col, value=_num(val))
        cell.number_format = '#,##0.00'
        cell.font = BOLD
        cell.alignment = RIGHT
    _style_range(ws, f'A{r}:J{r}')

    # ── Approvals ───────────────────────────────────────────────────────
    r += 3
    ws.cell(row=r, column=1, value='Negotiated By:').font = BOLD
    ws.cell(row=r, column=3, value='Checked By:').font = BOLD
    r += 2
    ws.cell(row=r, column=1, value='_______________________').font = NORMAL
    ws.cell(row=r, column=3, value='_______________________').font = NORMAL
    r += 1
    ws.cell(row=r, column=1, value=pi.negotiated_by or '').font = BOLD
    ws.cell(row=r, column=3, value=pi.checked_by or '').font = BOLD


def build_pi_workbook(pi):
    """Return an in-memory .xlsx (BytesIO) for the given ProformaInvoice."""
    items = list(pi.items.select_related('product', 'requisition_item').all())
    currency = pi.currency or 'INR'
    symbol = '₹' if currency == 'INR' else ('$' if currency == 'USD' else currency)

    wb = Workbook()
    pi_ws = wb.active
    pi_ws.title = 'PI'
    _build_pi_sheet(pi_ws, pi, items, symbol)

    note_ws = wb.create_sheet('Sheet1')
    _build_note_sheet(note_ws, pi, items, symbol)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
