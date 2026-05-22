"""
POS System - Simple Invoice Generator
Backend: FastAPI + Neon PostgreSQL + ReportLab

Phase 1: Basic setup with health check and CORS
Phase 2: Invoice form, database integration
Phase 3: PDF invoice generation and download
"""

import os
import io
import json
from datetime import datetime
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
import psycopg

# ── ReportLab imports for PDF generation ────────────────────────────
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT

# ── Load environment variables from .env ────────────────────────────
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")


# ═══════════════════════════════════════════════════════════════════
# Pydantic Models — These validate the incoming request data
# ═══════════════════════════════════════════════════════════════════

class InvoiceItem(BaseModel):
    """A single product line in an invoice."""
    product_name: str
    quantity: int
    price: float

    # Validate that product name is not empty
    @field_validator("product_name")
    @classmethod
    def product_name_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("Product name cannot be empty")
        return v.strip()

    # Validate that quantity is at least 1
    @field_validator("quantity")
    @classmethod
    def quantity_must_be_positive(cls, v):
        if v < 1:
            raise ValueError("Quantity must be at least 1")
        return v

    # Validate that price is greater than 0
    @field_validator("price")
    @classmethod
    def price_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError("Price must be greater than 0")
        return v


class InvoiceRequest(BaseModel):
    """The full invoice request body."""
    customer_name: str
    items: List[InvoiceItem]

    # Validate that customer name is not empty
    @field_validator("customer_name")
    @classmethod
    def customer_name_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("Customer name cannot be empty")
        return v.strip()

    # Validate that at least one product is provided
    @field_validator("items")
    @classmethod
    def items_not_empty(cls, v):
        if len(v) == 0:
            raise ValueError("At least one product is required")
        return v


# ═══════════════════════════════════════════════════════════════════
# Create the FastAPI app
# ═══════════════════════════════════════════════════════════════════

app = FastAPI(
    title="POS Invoice Generator",
    description="A simple POS system to generate PDF invoices",
    version="3.0.0",
)

# ── CORS setup (allow Next.js frontend to call this backend) ───────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",   # Next.js dev server
        "http://localhost:3001",   # Next.js alternate port
    ],
    allow_credentials=True,
    allow_methods=["*"],           # Allow all HTTP methods
    allow_headers=["*"],           # Allow all headers
)


# ═══════════════════════════════════════════════════════════════════
# Database Helper
# ═══════════════════════════════════════════════════════════════════

def get_db_connection():
    """
    Create and return a database connection using DATABASE_URL.
    Raises HTTPException(500) if the connection fails.
    """
    # Check if DATABASE_URL is set
    if not DATABASE_URL:
        raise HTTPException(
            status_code=500,
            detail="DATABASE_URL is not set in .env file. Please add your Neon connection string.",
        )

    # Try to connect to the database
    try:
        conn = psycopg.connect(DATABASE_URL)
        return conn
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to connect to database: {str(e)}",
        )


# ═══════════════════════════════════════════════════════════════════
# Auto-create tables on startup
# ═══════════════════════════════════════════════════════════════════

@app.on_event("startup")
def create_tables():
    """
    Create the invoices table if it doesn't exist.
    This runs automatically when the server starts.
    """
    if not DATABASE_URL:
        print("WARNING: DATABASE_URL not set. Database features won't work.")
        print("   Add your Neon connection string to backend/.env")
        return

    try:
        conn = psycopg.connect(DATABASE_URL)
        cursor = conn.cursor()

        # Create the pos_invoices table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pos_invoices (
                id SERIAL PRIMARY KEY,
                customer_name VARCHAR(100),
                items JSONB,
                total_amount NUMERIC,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        conn.commit()
        cursor.close()
        conn.close()
        print("Database connected & invoices table ready!")

    except Exception as e:
        print(f"Database setup failed: {e}")
        print("   The server will still run, but invoice saving won't work.")


# ═══════════════════════════════════════════════════════════════════
# PDF Generation Helper
# ═══════════════════════════════════════════════════════════════════

def generate_pdf(invoice_id, customer_name, items_with_totals, grand_total, created_at):
    """
    Generate a PDF invoice using ReportLab.

    Args:
        invoice_id: The database ID of the invoice
        customer_name: Name of the customer
        items_with_totals: List of items with calculated totals
        grand_total: The grand total amount
        created_at: When the invoice was created

    Returns:
        A BytesIO buffer containing the PDF data
    """

    # Step 1: Create a buffer to hold the PDF in memory
    buffer = io.BytesIO()

    # Step 2: Create the PDF document (A4 paper size)
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    # Step 3: Set up text styles
    styles = getSampleStyleSheet()

    # Title style — big, bold, centered
    title_style = ParagraphStyle(
        "InvoiceTitle",
        parent=styles["Heading1"],
        fontSize=22,
        textColor=colors.HexColor("#1a1a2e"),
        alignment=TA_CENTER,
        spaceAfter=6 * mm,
    )

    # Subtitle style — for invoice details
    subtitle_style = ParagraphStyle(
        "InvoiceSubtitle",
        parent=styles["Normal"],
        fontSize=11,
        textColor=colors.HexColor("#444444"),
        alignment=TA_CENTER,
        spaceAfter=2 * mm,
    )

    # Normal text style
    normal_style = ParagraphStyle(
        "InvoiceNormal",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#333333"),
    )

    # Grand total style — right-aligned, bold
    total_style = ParagraphStyle(
        "InvoiceTotal",
        parent=styles["Normal"],
        fontSize=13,
        textColor=colors.HexColor("#1a1a2e"),
        alignment=TA_RIGHT,
        fontName="Helvetica-Bold",
        spaceBefore=4 * mm,
    )

    # Step 4: Build the PDF content (list of elements)
    elements = []

    # --- Title ---
    elements.append(Paragraph("POS INVOICE", title_style))

    # --- Horizontal line ---
    line_data = [["" ]]
    line_table = Table(line_data, colWidths=[170 * mm])
    line_table.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#6366f1")),
    ]))
    elements.append(line_table)
    elements.append(Spacer(1, 4 * mm))

    # --- Invoice details (ID, customer, date) ---
    elements.append(Paragraph(f"<b>Invoice ID:</b> #{invoice_id}", normal_style))
    elements.append(Spacer(1, 2 * mm))
    elements.append(Paragraph(f"<b>Customer:</b> {customer_name}", normal_style))
    elements.append(Spacer(1, 2 * mm))
    elements.append(Paragraph(f"<b>Date:</b> {created_at}", normal_style))
    elements.append(Spacer(1, 8 * mm))

    # --- Product table ---
    # Table header row
    table_data = [["#", "Product", "Qty", "Price", "Total"]]

    # Table data rows — one row per product
    for i, item in enumerate(items_with_totals, 1):
        table_data.append([
            str(i),
            item["product_name"],
            str(item["quantity"]),
            f"Rs.{item['price']:.2f}",
            f"Rs.{item['item_total']:.2f}",
        ])

    # Create the table with column widths
    product_table = Table(
        table_data,
        colWidths=[12 * mm, 70 * mm, 20 * mm, 35 * mm, 35 * mm],
    )

    # Style the table (colors, borders, fonts)
    product_table.setStyle(TableStyle([
        # Header row styling
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#6366f1")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),

        # Data rows styling
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ALIGN", (0, 1), (0, -1), "CENTER"),   # # column centered
        ("ALIGN", (2, 1), (2, -1), "CENTER"),   # Qty column centered
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"),   # Price & Total right-aligned
        ("TOPPADDING", (0, 1), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 6),

        # Alternating row colors for readability
        *[
            ("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f0f0ff"))
            for i in range(2, len(table_data), 2)
        ],

        # Grid lines
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("LINEBELOW", (0, 0), (-1, 0), 1.5, colors.HexColor("#4f46e5")),
    ]))

    elements.append(product_table)
    elements.append(Spacer(1, 6 * mm))

    # --- Grand Total ---
    elements.append(Paragraph(f"Grand Total: Rs.{grand_total:.2f}", total_style))
    elements.append(Spacer(1, 10 * mm))

    # --- Footer line ---
    elements.append(line_table)
    elements.append(Spacer(1, 3 * mm))

    footer_style = ParagraphStyle(
        "Footer",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.HexColor("#999999"),
        alignment=TA_CENTER,
    )
    elements.append(Paragraph("Thank you for your business!", footer_style))
    elements.append(Paragraph("Generated by POS Invoice Generator", footer_style))

    # Step 5: Build the PDF
    doc.build(elements)

    # Step 6: Reset buffer position to the beginning so it can be read
    buffer.seek(0)

    return buffer


# ═══════════════════════════════════════════════════════════════════
# Routes
# ═══════════════════════════════════════════════════════════════════

# ── Health check route ─────────────────────────────────────────────
@app.get("/")
def health_check():
    """
    Health check endpoint.
    Returns a simple JSON to confirm the backend is running.
    """
    return {
        "status": "ok",
        "message": "POS Invoice Generator API is running!",
    }


# ── Generate Invoice endpoint ──────────────────────────────────────
@app.post("/generate-invoice")
def generate_invoice(invoice: InvoiceRequest):
    """
    Create a new invoice, save to database, generate PDF, and return it.

    Steps:
    1. Validate the input (Pydantic handles this automatically)
    2. Calculate item totals and grand total
    3. Save to PostgreSQL database
    4. Generate a PDF invoice
    5. Return the PDF as a downloadable file
    """

    # ── Step 1: Calculate totals ────────────────────────────────────
    items_with_totals = []
    grand_total = 0

    for item in invoice.items:
        # Calculate total for this item (quantity x price)
        item_total = item.quantity * item.price
        grand_total += item_total

        items_with_totals.append({
            "product_name": item.product_name,
            "quantity": item.quantity,
            "price": item.price,
            "item_total": round(item_total, 2),
        })

    grand_total = round(grand_total, 2)

    # ── Step 2: Save to database ────────────────────────────────────
    conn = get_db_connection()

    try:
        cursor = conn.cursor()

        # Insert the invoice into the database
        cursor.execute(
            """
            INSERT INTO pos_invoices (customer_name, items, total_amount)
            VALUES (%s, %s, %s)
            RETURNING id, created_at;
            """,
            (
                invoice.customer_name,
                json.dumps(items_with_totals),
                grand_total,
            ),
        )

        # Get the new invoice ID and creation date
        row = cursor.fetchone()
        invoice_id = row[0]
        created_at = row[1]

        conn.commit()
        cursor.close()
        conn.close()

    except HTTPException:
        # Re-raise HTTP exceptions from get_db_connection
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save invoice to database: {str(e)}",
        )

    # ── Step 3: Generate PDF ────────────────────────────────────────
    # Format the date nicely for the PDF
    date_str = created_at.strftime("%d %B %Y, %I:%M %p") if created_at else "N/A"

    try:
        pdf_buffer = generate_pdf(
            invoice_id=invoice_id,
            customer_name=invoice.customer_name,
            items_with_totals=items_with_totals,
            grand_total=grand_total,
            created_at=date_str,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate PDF: {str(e)}",
        )

    # ── Step 4: Return the PDF as a downloadable file ───────────────
    filename = f"invoice_{invoice_id}.pdf"

    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
