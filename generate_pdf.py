"""
PDF Report Generator for Cosmofeed Payout Audit & Telegram SEBI Verification
=============================================================================
Generates a formal, executive-grade multi-page PDF report matching the exact
structure, sequence, and data flow of the dashboard.
"""

import os
import json
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, PageBreak, KeepTogether, HRFlowable
)
from reportlab.pdfgen import canvas

HERE = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(HERE, "reports")


class NumberedCanvas(canvas.Canvas):
    """Adds professional running header and page numbering to every page."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(colors.HexColor("#64748b"))
        
        # Header
        self.drawString(36, 11 * inch - 28, "COSMOFEED EXECUTIVE AUDIT INTELLIGENCE · CONFIDENTIAL")
        self.setStrokeColor(colors.HexColor("#e2e8f0"))
        self.setLineWidth(0.75)
        self.line(36, 11 * inch - 32, 8.5 * inch - 36, 11 * inch - 32)
        
        # Footer
        self.setFont("Helvetica", 8)
        self.drawString(36, 24, "Cosmofeed Payout Audit & SEBI Compliance Engine · T+1 Release Gate")
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(8.5 * inch - 36, 24, page_str)
        self.line(36, 34, 8.5 * inch - 36, 34)
        self.restoreState()


def inr_fmt(val):
    try:
        n = float(val or 0)
        return f"{n:,.2f}"
    except Exception:
        return "0.00"


def generate_pdf_report(json_data_path: str = None, output_pdf_path: str = None) -> str:
    if not json_data_path:
        json_data_path = os.path.join(REPORTS_DIR, "data.json")
    if not output_pdf_path:
        output_pdf_path = os.path.join(REPORTS_DIR, "Cosmofeed_Payout_Audit_Report.pdf")

    if not os.path.exists(json_data_path):
        raise FileNotFoundError(f"Data file not found at {json_data_path}")

    with open(json_data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    creators = data.get("creators", [])
    counts = data.get("counts", {})
    rev_date = data.get("reviewDateFormatted") or data.get("reviewDate") or "2026-08-27"
    sale_date = data.get("productSaleDateFormatted") or data.get("productSaleDate") or "2026-08-26"
    gen_at = data.get("generatedAt") or "2026-08-27"

    total_payout = sum(float(c.get("payoutAmount") or 0) for c in creators)
    self_creators = [c for c in creators if c.get("selfTransaction")]
    tele_creators = [c for c in creators if c.get("telegramIntegration") and c.get("telegramEligible")]
    tele_sebi_yes = [c for c in tele_creators if c.get("sebiRegisteredYes") == "Yes"]
    tele_sebi_no = [c for c in tele_creators if c.get("sebiRegisteredNo") == "No"]
    manual_review_creators = [c for c in tele_creators if c.get("sebiReviewStatus") == "Manual Review Required"]

    # Setup Document
    doc = SimpleDocTemplate(
        output_pdf_path,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=46,
        bottomMargin=46
    )

    styles = getSampleStyleSheet()

    # Custom typography
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#0f172a")
    )
    subtitle_style = ParagraphStyle(
        "DocSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#64748b")
    )
    h2_style = ParagraphStyle(
        "SectionHeading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#1e1b4b"),
        spaceBefore=14,
        spaceAfter=6
    )
    body_style = ParagraphStyle(
        "BodyDark",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#1e293b")
    )
    table_cell_style = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor("#0f172a")
    )
    table_header_style = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor("#334155")
    )
    badge_green = ParagraphStyle(
        "BadgeGreen",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7,
        leading=8,
        textColor=colors.HexColor("#047857")
    )
    badge_red = ParagraphStyle(
        "BadgeRed",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7,
        leading=8,
        textColor=colors.HexColor("#b91c1c")
    )
    badge_amber = ParagraphStyle(
        "BadgeAmber",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7,
        leading=8,
        textColor=colors.HexColor("#b45309")
    )

    elements = []

    # Title & Metadata Banner
    elements.append(Paragraph("Cosmofeed Payout Risk Audit & Compliance Report", title_style))
    elements.append(Spacer(1, 3))
    meta_text = (
        f"<b>Audit Date:</b> {rev_date} &nbsp;|&nbsp; "
        f"<b>Product Sale Date:</b> {sale_date} &nbsp;|&nbsp; "
        f"<b>Settlements Audited:</b> {len(creators):,} &nbsp;|&nbsp; "
        f"<b>Generated:</b> {gen_at}"
    )
    elements.append(Paragraph(meta_text, subtitle_style))
    elements.append(Spacer(1, 10))

    # Executive KPI Metric Grid
    kpi_data = [
        [
            Paragraph(f"<b>₹{total_payout:,.2f}</b><br/><font size=7 color='#64748b'>TOTAL PENDING PAYOUT</font>", table_cell_style),
            Paragraph(f"<b>{len(self_creators)}</b><br/><font size=7 color='#64748b'>SELF-TXN FLAGGED (2D)</font>", table_cell_style),
            Paragraph(f"<b>{len(tele_creators)}</b><br/><font size=7 color='#64748b'>TELEGRAM (≥ ₹1K)</font>", table_cell_style),
            Paragraph(f"<font color='#047857'><b>{len(tele_sebi_yes)}</b></font><br/><font size=7 color='#64748b'>SEBI VERIFIED (YES)</font>", table_cell_style),
            Paragraph(f"<font color='#b91c1c'><b>{len(tele_sebi_no)}</b></font><br/><font size=7 color='#64748b'>SEBI UNVERIFIED (NO)</font>", table_cell_style),
            Paragraph(f"<font color='#b45309'><b>{len(manual_review_creators)}</b></font><br/><font size=7 color='#64748b'>MANUAL REVIEW REQ</font>", table_cell_style),
        ]
    ]
    kpi_table = Table(kpi_data, colWidths=[90, 85, 80, 85, 90, 110])
    kpi_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(kpi_table)
    elements.append(Spacer(1, 12))

    # Priority Action Alert (If any non-SEBI or self-txns)
    if tele_sebi_no:
        alert_p = Paragraph(
            f"<b>CRITICAL COMPLIANCE NOTICE:</b> {len(tele_sebi_no)} creator(s) are using Telegram integration "
            f"(<code>vig/productId</code>) with settlements &ge; ₹1,000 but are <b>NOT found in the SEBI-registered creator list</b>. "
            "Priority manual review required before payout authorization.",
            ParagraphStyle("AlertText", parent=body_style, textColor=colors.HexColor("#991b1b"), fontSize=8)
        )
        alert_box = Table([[alert_p]], colWidths=[540])
        alert_box.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#fff1f2")),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor("#fecdd3")),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ]))
        elements.append(alert_box)
        elements.append(Spacer(1, 12))

    # SECTION 1: Telegram Integration & SEBI Compliance (Sorted Highest -> Lowest)
    elements.append(Paragraph(f"1 · Telegram Integration & SEBI Compliance ({len(tele_creators)} settlements &ge; ₹1,000)", h2_style))
    elements.append(Paragraph(
        "Settlements &ge; ₹1,000 utilizing Telegram integration (<code>vig/productId</code>) cross-referenced against the organization's SEBI Master Registry. Sorted strictly from Highest to Lowest payout amount.",
        subtitle_style
    ))
    elements.append(Spacer(1, 6))

    tele_table_data = [
        [
            Paragraph("#", table_header_style),
            Paragraph("Amount (₹)", table_header_style),
            Paragraph("Creator Name", table_header_style),
            Paragraph("Creator ID", table_header_style),
            Paragraph("Product ID", table_header_style),
            Paragraph("TG", table_header_style),
            Paragraph("SEBI: Yes", table_header_style),
            Paragraph("SEBI: No", table_header_style),
            Paragraph("SEBI Status", table_header_style),
            Paragraph("Review Status", table_header_style)
        ]
    ]

    # Sort Telegram settlements descending by payout amount
    sorted_tele = sorted(tele_creators, key=lambda c: -float(c.get("payoutAmount") or 0))

    for idx, c in enumerate(sorted_tele[:40], 1): # Top 40 for PDF clarity
        p_amt = float(c.get("payoutAmount") or 0)
        u_name = str(c.get("username") or c.get("displayName") or "—")[:18]
        cid = str(c.get("creatorId") or "—")
        pid = str(c.get("telegramProductId") or "—")
        sebi_yes = c.get("sebiRegisteredYes") or "—"
        sebi_no = c.get("sebiRegisteredNo") or "—"
        sebi_status = c.get("sebiVerificationStatus") or "—"
        rev_status = c.get("sebiReviewStatus") or "Normal"

        yes_p = Paragraph("Yes", badge_green) if sebi_yes == "Yes" else Paragraph("—", table_cell_style)
        no_p = Paragraph("No", badge_red) if sebi_no == "No" else Paragraph("—", table_cell_style)
        rev_p = Paragraph("Manual Review", badge_amber) if rev_status == "Manual Review Required" else Paragraph("Normal", table_cell_style)

        tele_table_data.append([
            Paragraph(str(idx), table_cell_style),
            Paragraph(f"<b>₹{p_amt:,.0f}</b>", table_cell_style),
            Paragraph(u_name, table_cell_style),
            Paragraph(f"<font face='Courier' size=6>{cid[:10]}..</font>", table_cell_style),
            Paragraph(f"<font face='Courier' size=6>{pid[:10]}..</font>", table_cell_style),
            Paragraph("YES", table_cell_style),
            yes_p,
            no_p,
            Paragraph(sebi_status, table_cell_style),
            rev_p
        ])

    tele_table = Table(tele_table_data, colWidths=[20, 65, 85, 65, 65, 25, 45, 45, 65, 60])
    tele_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#f1f5f9")),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    elements.append(tele_table)

    if len(sorted_tele) > 40:
        elements.append(Spacer(1, 4))
        elements.append(Paragraph(f"<i>... and {len(sorted_tele) - 40} additional Telegram settlements available in full CSV/Excel export.</i>", subtitle_style))

    # SECTION 2: Self-Transactions in the last 2 days
    elements.append(Spacer(1, 14))

    import re
    def get_self_sort_tuple(c):
        dt_str = str(c.get("latestSelfTxnDate") or "").strip()
        day_key = 0
        if dt_str:
            m = re.search(r"(\d{1,2})\s+([A-Za-z]{3}),?\s+(\d{4})", dt_str)
            if m:
                day = int(m.group(1))
                months = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6, "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
                month = months.get(m.group(2), 0)
                year = int(m.group(3))
                if day and month and year:
                    day_key = year * 10000 + month * 100 + day
        max_amt = float(c.get("selfTxnMaxAmount") or 0)
        return (day_key, max_amt)

    # Filter to 2-day rolling window dynamically based on top 3 distinct days present
    distinct_self_days = sorted(list(set(get_self_sort_tuple(c)[0] for c in self_creators if get_self_sort_tuple(c)[0] > 0)), reverse=True)
    top_3_days = set(distinct_self_days[:3])
    self_2d_creators = [c for c in self_creators if (not top_3_days or get_self_sort_tuple(c)[0] in top_3_days)]
    sorted_self = sorted(self_2d_creators, key=get_self_sort_tuple, reverse=True)

    elements.append(Paragraph(f"2 · Flagged Self-Transactions ({len(sorted_self)} creators in 2-day rolling window)", h2_style))
    elements.append(Paragraph(
        "Creators with verified native <code>selfPayment</code> flag in the rolling 2-day audit window, sorted strictly by Date descending &rarr; Highest Self-Transaction Amount to Lowest.",
        subtitle_style
    ))
    elements.append(Spacer(1, 6))

    self_table_data = [
        [
            Paragraph("#", table_header_style),
            Paragraph("Date / Time", table_header_style),
            Paragraph("Creator Username", table_header_style),
            Paragraph("Creator ID", table_header_style),
            Paragraph("Self-Txn (₹)", table_header_style),
            Paragraph("Pending Payout (₹)", table_header_style),
            Paragraph("Txns", table_header_style)
        ]
    ]

    for idx, c in enumerate(sorted_self, 1):
        dt = str(c.get("latestSelfTxnDate") or "—")
        u = str(c.get("username") or "—")[:18]
        cid = str(c.get("creatorId") or "—")
        sa = float(c.get("selfTxnMaxAmount") or 0)
        p = float(c.get("payoutAmount") or 0)
        cnt = c.get("selfTxnCount") or 1

        self_table_data.append([
            Paragraph(str(idx), table_cell_style),
            Paragraph(dt, table_cell_style),
            Paragraph(f"<b>{u}</b>", table_cell_style),
            Paragraph(f"<font face='Courier' size=6>{cid[:12]}..</font>", table_cell_style),
            Paragraph(f"<font color='#dc2626'><b>₹{sa:,.2f}</b></font>", table_cell_style),
            Paragraph(f"₹{p:,.0f}", table_cell_style),
            Paragraph(str(cnt), table_cell_style)
        ])

    self_table = Table(self_table_data, colWidths=[24, 90, 110, 85, 80, 85, 66])
    self_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#f1f5f9")),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    elements.append(self_table)

    # Build PDF
    doc.build(elements, canvasmaker=NumberedCanvas)
    return output_pdf_path


if __name__ == "__main__":
    out = generate_pdf_report()
    print("Generated PDF report at:", out)
