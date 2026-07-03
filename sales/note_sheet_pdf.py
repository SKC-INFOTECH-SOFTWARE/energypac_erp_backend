"""
Landscape PDF of the Note Sheet / Comparative Statement (Excel "Sheet1").

Renders the SAME data as the Excel note sheet (via `compute_note_sheet`) so the
two always agree. The table auto-fits the A4-landscape page width: column widths
are scaled to the available width and the font shrinks as more vendor columns
appear, so everything stays on one page width regardless of vendor count.
"""
from io import BytesIO

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

from .excel_export import compute_note_sheet, _fmt_date, _num

HEAD_BG = colors.HexColor('#E5E7EB')
GRID = colors.HexColor('#333333')


def build_note_sheet_pdf(pi):
    """Return an in-memory landscape .pdf (BytesIO) of the PI's Note Sheet."""
    items = list(pi.items.select_related('product', 'requisition_item').all())
    data = compute_note_sheet(pi, items)

    cur = data['currency']
    vendors = data['vendor_order']
    generic = data['generic']
    V = len(vendors)
    rows = data['rows']
    tot = data['totals']
    profit_pct = data['profit_pct']

    # Auto-fit: shrink the base font as columns grow.
    total_cols = 11 + 2 * V
    fs = 7.0 if total_cols <= 12 else max(5.0, 7.0 - (total_cols - 12) * 0.25)

    page = landscape(A4)
    margin = 8 * mm
    avail_w = page[0] - 2 * margin

    def para(text, align=TA_LEFT, bold=False, size=None):
        s = size or fs
        st = ParagraphStyle(
            'c', fontName='Helvetica-Bold' if bold else 'Helvetica',
            fontSize=s, leading=s + 1.6, alignment=align,
        )
        txt = '' if text is None else str(text).replace('\n', '<br/>')
        return Paragraph(txt, st)

    def numcell(v, bold=False):
        if v is None:
            return para('', TA_RIGHT, bold)
        return para(f"{float(v):,.2f}", TA_RIGHT, bold)

    def scaled(weights):
        tw = sum(weights)
        return [w / tw * avail_w for w in weights]

    # ── Column geometry (0-indexed) for Section 1 ──
    c_sl, c_desc, c_uom, c_qty = 0, 1, 2, 3
    c_v0 = 4
    c_act = c_v0 + 2 * V        # Actual Purchase Price (from PO) — single col
    c_new = c_act + 1
    c_last = c_new + 2
    c_rem = c_last + 3
    ncols = c_rem + 1

    # Column weights → auto-fit widths
    w = [0.6, 4.2, 0.9, 0.9]
    for _ in range(V):
        w += [1.15, 1.25]
    w += [1.3]                 # actual purchase (PO)
    w += [1.25, 1.25]          # new sale unit, total
    w += [2.0, 1.15, 1.25]     # last sale: LC, last unit, total
    w += [1.6]                 # remarks
    col_widths = scaled(w)

    # ── Header rows ──
    row0 = [''] * ncols
    row0[c_sl] = para('ITEM DETAILS', TA_CENTER, bold=True)
    for i, vname in enumerate(vendors):
        title = 'Offer (Ex. works) / Last Supply' if generic else f'{vname}\nOffer / Last Supply'
        row0[c_v0 + 2 * i] = para(title, TA_CENTER, bold=True)
    row0[c_act] = para(f'Actual Purchase Price (PO)\n{cur}', TA_CENTER, bold=True)
    row0[c_new] = para('New Sale Price from Kolkata office', TA_CENTER, bold=True)
    row0[c_last] = para('Last Sale Price from Kolkata office', TA_CENTER, bold=True)
    row0[c_rem] = para('REMARKS', TA_CENTER, bold=True)

    row1 = [''] * ncols
    row1[c_sl] = para('Sl. No.', TA_CENTER, bold=True)
    row1[c_desc] = para('Description', TA_CENTER, bold=True)
    row1[c_uom] = para('U.O.M', TA_CENTER, bold=True)
    row1[c_qty] = para('QTY', TA_CENTER, bold=True)
    for i in range(V):
        row1[c_v0 + 2 * i] = para(f'Unit Price\n(Ex. works)\n{cur}', TA_CENTER, bold=True)
        row1[c_v0 + 2 * i + 1] = para(f'Total Price\n(Ex. works)\n{cur}', TA_CENTER, bold=True)
    row1[c_new] = para(f'Unit Price\n(CPT, BENAPOLE)\n{cur}', TA_CENTER, bold=True)
    row1[c_new + 1] = para(f'Total Price\n(CPT, BENAPOLE)\n{cur}', TA_CENTER, bold=True)
    row1[c_last] = para('LC NO & DATE', TA_CENTER, bold=True)
    row1[c_last + 1] = para('LAST UNIT PRICE', TA_CENTER, bold=True)
    row1[c_last + 2] = para(f'Total Price\n(CPT, BENAPOLE)\n{cur}', TA_CENTER, bold=True)

    table_data = [row0, row1]

    for row in rows:
        tr = [
            para(row['sl'], TA_CENTER),
            para(row['description'], TA_LEFT),
            para(row['unit'], TA_CENTER),
            numcell(row['qty']),
        ]
        for i in range(V):
            tr.append(numcell(row['vendor_rates'][i]))
            tr.append(numcell(row['vendor_totals'][i]))
        tr.append(numcell(row['actual_rate']))
        tr += [
            numcell(row['sale_unit']), numcell(row['cpt_total']),
            para(row['lc_ref'], TA_LEFT), numcell(row['last_unit']), numcell(row['last_total']),
            para('', TA_LEFT),
        ]
        table_data.append(tr)

    # Totals row
    tr = [''] * ncols
    tr[c_sl] = para('Total Amount', TA_RIGHT, bold=True)
    for i in range(V):
        tr[c_v0 + 2 * i + 1] = numcell(tot['vendor'][i], bold=True)
    tr[c_act] = numcell(tot['actual'], bold=True)
    tr[c_new + 1] = numcell(tot['new'], bold=True)
    tr[c_last + 2] = numcell(tot['last'], bold=True)
    table_data.append(tr)

    total_row_idx = len(table_data) - 1

    style = [
        ('GRID', (0, 0), (-1, -1), 0.5, GRID),
        ('BACKGROUND', (0, 0), (-1, 1), HEAD_BG),
        ('BACKGROUND', (0, total_row_idx), (-1, total_row_idx), HEAD_BG),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('SPAN', (c_sl, 0), (c_qty, 0)),
        ('SPAN', (c_act, 0), (c_act, 1)),
        ('SPAN', (c_new, 0), (c_new + 1, 0)),
        ('SPAN', (c_last, 0), (c_last + 2, 0)),
        ('SPAN', (c_rem, 0), (c_rem, 1)),
        ('SPAN', (c_sl, total_row_idx), (c_qty, total_row_idx)),
    ]
    for i in range(V):
        style.append(('SPAN', (c_v0 + 2 * i, 0), (c_v0 + 2 * i + 1, 0)))

    section1 = Table(table_data, colWidths=col_widths, repeatRows=2)
    section1.setStyle(TableStyle(style))

    # ── Section 2: price break-up (fixed 10 columns) ──
    s2w = [0.6, 4.5, 0.9, 0.9, 1.4, 1.4, 1.1, 1.2, 1.3, 1.4]
    s2_widths = scaled(s2w)
    s2_head = [
        para('Sl. No.', TA_CENTER, bold=True),
        para('Description', TA_CENTER, bold=True),
        para('U.O.M', TA_CENTER, bold=True),
        para('QTY', TA_CENTER, bold=True),
        para(f'Purchase Unit Price\n(Ex. works)\n{cur}', TA_CENTER, bold=True),
        para(f'Total Purchase\n(Ex. works)\n{cur}', TA_CENTER, bold=True),
        para('Freight', TA_CENTER, bold=True),
        para('Export Cost', TA_CENTER, bold=True),
        para(f'Profit Loading\n@ {_num(profit_pct):g}%', TA_CENTER, bold=True),
        para(f'Total Amount\n(CPT Benapole)\n{cur}', TA_CENTER, bold=True),
    ]
    s2_data = [s2_head]
    for row in rows:
        s2_data.append([
            para(row['sl'], TA_CENTER),
            para(row['description'], TA_LEFT),
            para(row['unit'], TA_CENTER),
            numcell(row['qty']),
            numcell(row['p_rate']),
            numcell(row['purchase_total']),
            numcell(row['freight']),
            numcell(row['export_cost']),
            numcell(row['profit']),
            numcell(row['cpt2']),
        ])
    s2_total = ['', '', '', para('Total Amount', TA_RIGHT, bold=True),
                '', numcell(tot['purchase'], bold=True), numcell(tot['freight'], bold=True),
                numcell(tot['export'], bold=True), numcell(tot['profit'], bold=True),
                numcell(tot['cpt2'], bold=True)]
    s2_data.append(s2_total)
    s2_total_idx = len(s2_data) - 1

    section2 = Table(s2_data, colWidths=s2_widths, repeatRows=1)
    section2.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, GRID),
        ('BACKGROUND', (0, 0), (-1, 0), HEAD_BG),
        ('BACKGROUND', (0, s2_total_idx), (-1, s2_total_idx), HEAD_BG),
        ('SPAN', (0, s2_total_idx), (3, s2_total_idx)),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))

    # ── Approvals ──
    approvals = Table([
        [para('Negotiated By:', TA_LEFT, bold=True), para('Checked By:', TA_LEFT, bold=True)],
        [para('_______________________', TA_LEFT), para('_______________________', TA_LEFT)],
        [para(pi.negotiated_by or '', TA_LEFT, bold=True), para(pi.checked_by or '', TA_LEFT, bold=True)],
    ], colWidths=[avail_w * 0.4, avail_w * 0.4])
    approvals.setStyle(TableStyle([
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))

    # ── Story ──
    title_style = ParagraphStyle('t', fontName='Helvetica-Bold', fontSize=12, alignment=TA_CENTER, spaceAfter=4)
    info_style = ParagraphStyle('i', fontName='Helvetica', fontSize=8, leading=11)
    story = [
        Paragraph('Comparative Statement / Note Sheet', title_style),
        Paragraph(f"<b>PI NO:-</b> {pi.pi_number}&nbsp;&nbsp;DT. {_fmt_date(pi.pi_date)}", info_style),
        Paragraph(f"<b>Project Name:</b> {pi.project_name or ''}", info_style),
        Paragraph(f"<b>Exchange Rate:</b> {_num(data['conversion_rate'])} PER {cur}", info_style),
        Spacer(1, 6),
        section1,
        Spacer(1, 12),
        Paragraph(f"<b>PROFORMA INVOICE NO:-</b> {pi.pi_number}&nbsp;&nbsp;DT. {_fmt_date(pi.pi_date)} "
                  f"&nbsp;&nbsp;— price breakup based on selected offer", info_style),
        Spacer(1, 4),
        section2,
        Spacer(1, 16),
        approvals,
    ]

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=page,
        leftMargin=margin, rightMargin=margin, topMargin=8 * mm, bottomMargin=8 * mm,
        title=f"Note Sheet {pi.pi_number}",
    )
    doc.build(story)
    buf.seek(0)
    return buf
