"""
PDF invoice generator.

Renders the customer-facing invoice PDF using ReportLab. Pulls branding
from COMPANY_CONFIG (env-driven). Layout is a modern SaaS / POS hybrid:
strong header with logo + brand block, prominent invoice title, structured
items table, dedicated totals summary box, branded footer.

First page is intentionally dense in visual structure (logo, title, table,
totals box) — this gives WhatsApp's preview pipeline reliable anchors to
render a thumbnail from.

All business math (totals, invoice numbering) is owned by main.py. This
module ONLY handles rendering.
"""

import io
import os
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


# Resolve assets relative to backend/ regardless of CWD.
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── Company / Branding Configuration ─────────────────────────────────
# Single source of truth for all branding text shown on the invoice.
# Override any field via env vars in backend/.env. Empty defaults keep
# the layout clean when no branding is supplied.
COMPANY_CONFIG = {
    # Empty default → no name line under the logo unless COMPANY_NAME is set.
    "name":      os.getenv("COMPANY_NAME", ""),
    "address":   os.getenv("COMPANY_ADDRESS", ""),
    "phone":     os.getenv("COMPANY_PHONE", ""),
    "email":     os.getenv("COMPANY_EMAIL", ""),
    "gst":       os.getenv("COMPANY_GST", ""),
    "website":   os.getenv("COMPANY_WEBSITE", ""),
    "tagline":   os.getenv("COMPANY_TAGLINE", "Powered by Kodryx"),
    # Relative paths resolve from backend/ (so default = backend/assets/logo.png).
    "logo_path": os.path.join(
        BACKEND_DIR,
        os.getenv("COMPANY_LOGO_PATH", "assets/logo.png"),
    ),
}


# ── Palette ──────────────────────────────────────────────────────────
BRAND       = colors.HexColor("#4f46e5")
BRAND_DARK  = colors.HexColor("#1e1b4b")
TEXT        = colors.HexColor("#111827")
TEXT_MUTED  = colors.HexColor("#6b7280")
BORDER      = colors.HexColor("#e5e7eb")
ROW_ALT     = colors.HexColor("#f9fafb")
SUMMARY_BG  = colors.HexColor("#eef2ff")

# Usable content width given the page margins below.
CONTENT_WIDTH = 174 * mm


def _resolve_logo_path() -> Optional[str]:
    """Return the first existing logo file.

    Tries the configured path first, then falls back to common image
    extensions in the same directory — so dropping in any of
    `logo.png` / `logo.jpg` / `logo.jpeg` / `logo.webp` works without
    setting COMPANY_LOGO_PATH explicitly.
    """
    configured = COMPANY_CONFIG.get("logo_path")
    if configured and os.path.isfile(configured):
        return configured
    if not configured:
        return None
    base, _ = os.path.splitext(configured)
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        candidate = base + ext
        if os.path.isfile(candidate):
            return candidate
    return None


def _build_logo_flowable(max_height_mm: float = 32, max_width_mm: float = 80):
    """Return a scaled Image flowable, or None if no usable logo exists.

    Aspect ratio is always preserved. Reads natural dimensions via Pillow
    (a reportlab transitive dep, so import is safe). Any failure path —
    missing file, unreadable image, Pillow absent — returns None so the
    caller can degrade gracefully.
    """
    path = _resolve_logo_path()
    if not path:
        return None
    try:
        from PIL import Image as PILImage
        with PILImage.open(path) as im:
            iw, ih = im.size
        if iw <= 0 or ih <= 0:
            return None
        max_w = max_width_mm * mm
        max_h = max_height_mm * mm
        scale = min(max_w / iw, max_h / ih)
        return Image(path, width=iw * scale, height=ih * scale, mask="auto")
    except Exception:
        return None


def _horizontal_rule(color, thickness: float = 0.5):
    """Full-width horizontal rule used as a section divider."""
    rule = Table([[""]], colWidths=[CONTENT_WIDTH])
    rule.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), thickness, color),
    ]))
    return rule


def generate_pdf(
    invoice_id: int,
    customer_name: str,
    items_with_totals: list,
    grand_total: float,
    created_at: str,
    customer_phone: Optional[str] = None,
) -> io.BytesIO:
    """Build the invoice PDF and return it as an in-memory buffer.

    Args mirror the legacy signature; `customer_phone` is new and optional
    so existing callers keep working without changes.
    """
    buffer = io.BytesIO()
    invoice_number = f"INV-{invoice_id}"

    # ── Document setup + PDF metadata ───────────────────────────────
    # SimpleDocTemplate forwards these into the canvas (setTitle/Author/
    # Subject/Creator). Document viewers — including WhatsApp's preview
    # pipeline — surface them as the document title and producer.
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Invoice {invoice_number}",
        author="Kodryx POS",
        subject="Transactional Invoice",
        creator="Kodryx POS System",
    )

    base = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "Title", parent=base["Heading1"], fontName="Helvetica-Bold",
        fontSize=24, leading=28, textColor=BRAND_DARK,
        alignment=TA_RIGHT, spaceAfter=4,
    )
    company_name_style = ParagraphStyle(
        "Company", parent=base["Normal"], fontName="Helvetica-Bold",
        fontSize=13, leading=16, textColor=TEXT, spaceBefore=0, spaceAfter=2,
    )
    company_meta_style = ParagraphStyle(
        "CompanyMeta", parent=base["Normal"], fontName="Helvetica",
        fontSize=8.5, leading=11, textColor=TEXT_MUTED,
    )
    meta_label_style = ParagraphStyle(
        "MetaLabel", parent=base["Normal"], fontName="Helvetica",
        fontSize=9.5, leading=13, textColor=TEXT, alignment=TA_RIGHT,
    )
    section_heading_style = ParagraphStyle(
        "SectionHeading", parent=base["Normal"], fontName="Helvetica-Bold",
        fontSize=9, leading=11, textColor=BRAND, spaceAfter=2,
    )
    bill_to_name_style = ParagraphStyle(
        "BillToName", parent=base["Normal"], fontName="Helvetica-Bold",
        fontSize=12, leading=15, textColor=TEXT,
    )
    bill_to_meta_style = ParagraphStyle(
        "BillToMeta", parent=base["Normal"], fontName="Helvetica",
        fontSize=9.5, leading=12, textColor=TEXT_MUTED,
    )
    footer_thanks_style = ParagraphStyle(
        "FooterThanks", parent=base["Normal"], fontName="Helvetica-Bold",
        fontSize=11, leading=14, textColor=BRAND_DARK, alignment=TA_CENTER,
    )
    footer_tagline_style = ParagraphStyle(
        "FooterTagline", parent=base["Normal"], fontName="Helvetica",
        fontSize=8.5, leading=11, textColor=TEXT_MUTED, alignment=TA_CENTER,
    )

    elements = []

    # ═══ HEADER ════════════════════════════════════════════════════
    # Left: logo + company info. Right: invoice title + metadata.
    logo = _build_logo_flowable()

    left_block = []
    if logo is not None:
        left_block.append(logo)
        left_block.append(Spacer(1, 3 * mm))
    if COMPANY_CONFIG["name"]:
        left_block.append(Paragraph(COMPANY_CONFIG["name"], company_name_style))
    if COMPANY_CONFIG["address"]:
        left_block.append(Paragraph(COMPANY_CONFIG["address"], company_meta_style))
    contact_bits = []
    if COMPANY_CONFIG["phone"]:
        contact_bits.append(COMPANY_CONFIG["phone"])
    if COMPANY_CONFIG["email"]:
        contact_bits.append(COMPANY_CONFIG["email"])
    if contact_bits:
        left_block.append(Paragraph(" · ".join(contact_bits), company_meta_style))
    if COMPANY_CONFIG["website"]:
        left_block.append(Paragraph(COMPANY_CONFIG["website"], company_meta_style))
    if COMPANY_CONFIG["gst"]:
        left_block.append(Paragraph(
            f"GST: {COMPANY_CONFIG['gst']}", company_meta_style))

    right_block = [
        Paragraph("BILLING INVOICE", title_style),
        Paragraph(f"<b>Invoice #:</b> {invoice_number}", meta_label_style),
        Paragraph(f"<b>Date:</b> {created_at}", meta_label_style),
    ]

    header_table = Table(
        [[left_block, right_block]],
        colWidths=[88 * mm, 86 * mm],
    )
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 6 * mm))
    elements.append(_horizontal_rule(BRAND, thickness=2))
    elements.append(Spacer(1, 7 * mm))

    # ═══ BILL TO ═══════════════════════════════════════════════════
    elements.append(Paragraph("BILL TO", section_heading_style))
    elements.append(Paragraph(customer_name, bill_to_name_style))
    if customer_phone:
        elements.append(Paragraph(customer_phone, bill_to_meta_style))
    elements.append(Spacer(1, 8 * mm))

    # ═══ ITEMS TABLE ═══════════════════════════════════════════════
    table_data = [["#", "Item", "Qty", "Price", "Subtotal"]]
    for i, item in enumerate(items_with_totals, 1):
        table_data.append([
            str(i),
            item["product_name"],
            str(item["quantity"]),
            f"Rs.{item['price']:.2f}",
            f"Rs.{item['item_total']:.2f}",
        ])

    items_table = Table(
        table_data,
        colWidths=[10 * mm, 78 * mm, 18 * mm, 32 * mm, 36 * mm],
    )
    table_style = [
        # Header
        ("BACKGROUND",   (0, 0), (-1, 0), BRAND),
        ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
        ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (-1, 0), 10),
        ("ALIGN",        (0, 0), (-1, 0), "CENTER"),
        ("TOPPADDING",   (0, 0), (-1, 0), 9),
        ("BOTTOMPADDING",(0, 0), (-1, 0), 9),
        # Body
        ("FONTNAME",     (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",     (0, 1), (-1, -1), 9.5),
        ("TEXTCOLOR",    (0, 1), (-1, -1), TEXT),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN",        (0, 1), (0, -1), "CENTER"),
        ("ALIGN",        (2, 1), (2, -1), "CENTER"),
        ("ALIGN",        (3, 1), (-1, -1), "RIGHT"),
        ("TOPPADDING",   (0, 1), (-1, -1), 7),
        ("BOTTOMPADDING",(0, 1), (-1, -1), 7),
        ("LEFTPADDING",  (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        # Borders
        ("BOX",          (0, 0), (-1, -1), 0.6, BORDER),
        ("INNERGRID",    (0, 1), (-1, -1), 0.3, BORDER),
    ]
    for i in range(2, len(table_data), 2):
        table_style.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))
    items_table.setStyle(TableStyle(table_style))
    elements.append(items_table)
    elements.append(Spacer(1, 8 * mm))

    # ═══ TOTALS SUMMARY BOX ════════════════════════════════════════
    # Pure visual restructure — `grand_total` from main.py is the source
    # of truth. Tax row is a 0.00 placeholder so the layout is ready for
    # future taxation without changing today's math.
    subtotal = grand_total
    tax_amount = 0.00
    final_total = grand_total

    summary_data = [
        ["Subtotal",     f"Rs.{subtotal:.2f}"],
        ["Tax",          f"Rs.{tax_amount:.2f}"],
        ["GRAND TOTAL",  f"Rs.{final_total:.2f}"],
    ]
    summary_table = Table(summary_data, colWidths=[36 * mm, 36 * mm])
    summary_table.setStyle(TableStyle([
        ("FONTNAME",     (0, 0), (-1, 1), "Helvetica"),
        ("FONTSIZE",     (0, 0), (-1, 1), 10),
        ("TEXTCOLOR",    (0, 0), (-1, 1), TEXT_MUTED),

        ("FONTNAME",     (0, 2), (-1, 2), "Helvetica-Bold"),
        ("FONTSIZE",     (0, 2), (-1, 2), 12.5),
        ("TEXTCOLOR",    (0, 2), (-1, 2), BRAND_DARK),
        ("BACKGROUND",   (0, 2), (-1, 2), SUMMARY_BG),

        ("ALIGN",        (0, 0), (0, -1), "LEFT"),
        ("ALIGN",        (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING",   (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 7),
        ("LEFTPADDING",  (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("BOX",          (0, 0), (-1, -1), 0.6, BORDER),
        ("LINEABOVE",    (0, 2), (-1, 2), 1.2, BRAND),
    ]))

    # Right-align the summary block by parking it in a wrapper table.
    summary_wrapper = Table(
        [["", summary_table]],
        colWidths=[102 * mm, 72 * mm],
    )
    summary_wrapper.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(summary_wrapper)
    elements.append(Spacer(1, 14 * mm))

    # ═══ FOOTER ════════════════════════════════════════════════════
    elements.append(_horizontal_rule(BORDER, thickness=0.5))
    elements.append(Spacer(1, 4 * mm))
    elements.append(Paragraph("Thank you for your purchase", footer_thanks_style))
    elements.append(Spacer(1, 1 * mm))
    elements.append(Paragraph(COMPANY_CONFIG["tagline"], footer_tagline_style))

    doc.build(elements)
    buffer.seek(0)
    return buffer
