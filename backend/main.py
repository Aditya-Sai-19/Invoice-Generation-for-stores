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
import re
from datetime import datetime
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator, model_validator
import psycopg

from services.kodryx_client import send_invoice_to_kodryx
from services.pdf_generator import generate_pdf

# ── Load environment variables from .env ────────────────────────────
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# Kodryx Social — communication infrastructure (WhatsApp delivery).
# POS only knows the endpoint + key; all WhatsApp orchestration lives there.
KODRYX_API_URL = os.getenv("KODRYX_API_URL")
KODRYX_API_KEY = os.getenv("KODRYX_API_KEY")

# Phone format used by both the InvoiceRequest validator and (mirrored) the frontend.
_PHONE_RE = re.compile(r"^\+?[1-9]\d{7,14}$")


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
    # POS still owns "customer data collection" — we just pass the phone
    # straight to Kodryx for delivery, never to Meta directly.
    customer_phone: Optional[str] = None
    send_via_whatsapp: bool = True

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

    # Normalize phone format if provided.
    @field_validator("customer_phone")
    @classmethod
    def normalize_phone(cls, v):
        if v is None:
            return None
        v = v.strip()
        if v == "":
            return None
        if not _PHONE_RE.match(v):
            raise ValueError(
                "customer_phone must be in E.164-like format, e.g. +919876543210"
            )
        return v

    # Phone is required only when WhatsApp delivery is requested.
    @model_validator(mode="after")
    def phone_required_when_whatsapp(self):
        if self.send_via_whatsapp and not self.customer_phone:
            raise ValueError(
                "customer_phone is required when send_via_whatsapp is true"
            )
        return self


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
    # X-Invoice-Id lets the frontend poll delivery status after download.
    expose_headers=["X-Invoice-Id", "Content-Disposition"],
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

        # Customer phone is collected by POS but used only as a Kodryx delivery
        # address — POS never calls a WhatsApp API directly.
        cursor.execute("""
            ALTER TABLE pos_invoices
            ADD COLUMN IF NOT EXISTS customer_phone VARCHAR(20);
        """)

        # Audit log for every Kodryx WhatsApp-delivery attempt. Doubles as the
        # cross-process idempotency record (PRIMARY KEY on invoice_id).
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS kodryx_delivery_log (
                invoice_id    INT PRIMARY KEY,
                customer_phone VARCHAR(20),
                status        VARCHAR(20) NOT NULL,
                response_code INT,
                response_body TEXT,
                error         TEXT,
                attempted_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        conn.commit()
        cursor.close()
        conn.close()
        print("Database connected & invoices table ready!")
        if not (KODRYX_API_URL and KODRYX_API_KEY):
            print(
                "WARN: KODRYX_API_URL / KODRYX_API_KEY not set — "
                "invoice generation still works, but WhatsApp delivery is disabled."
            )

    except Exception as e:
        print(f"Database setup failed: {e}")
        print("   The server will still run, but invoice saving won't work.")


# ═══════════════════════════════════════════════════════════════════
# PDF generation lives in services/pdf_generator.py — branding,
# layout, and ReportLab styling are owned there. Totals math stays here.
# ═══════════════════════════════════════════════════════════════════


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
def generate_invoice(invoice: InvoiceRequest, background_tasks: BackgroundTasks):
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
            INSERT INTO pos_invoices (customer_name, customer_phone, items, total_amount)
            VALUES (%s, %s, %s, %s)
            RETURNING id, created_at;
            """,
            (
                invoice.customer_name,
                invoice.customer_phone,
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
            customer_phone=invoice.customer_phone,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate PDF: {str(e)}",
        )

    # Snapshot the bytes ONCE so the same PDF can be both streamed to the
    # merchant and uploaded to Kodryx — never regenerated.
    pdf_bytes = pdf_buffer.getvalue()

    # ── Step 4: Schedule WhatsApp delivery (fire-and-forget) ────────
    # POS is responsible for billing + PDF only. Communication infra is
    # delegated to Kodryx; this call runs after the HTTP response is sent
    # and its failure can never block invoice generation or local download.
    if invoice.send_via_whatsapp and invoice.customer_phone:
        if KODRYX_API_URL and KODRYX_API_KEY:
            background_tasks.add_task(
                send_invoice_to_kodryx,
                invoice_id=invoice_id,
                pdf_bytes=pdf_bytes,
                customer_name=invoice.customer_name,
                customer_phone=invoice.customer_phone,
                amount=grand_total,
                db_url=DATABASE_URL,
                kodryx_url=KODRYX_API_URL,
                kodryx_api_key=KODRYX_API_KEY,
            )
        else:
            print(
                f"WARN: KODRYX_API_URL/KODRYX_API_KEY not set — "
                f"WhatsApp send skipped for invoice {invoice_id}."
            )

    # ── Step 5: Return the PDF as a downloadable file ───────────────
    filename = f"invoice_{invoice_id}.pdf"

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Invoice-Id": str(invoice_id),
        },
    )


# ── Delivery status endpoint (frontend polls this) ─────────────────
@app.get("/invoice-delivery-status/{invoice_id}")
def get_delivery_status(invoice_id: int):
    """
    Return the latest Kodryx delivery state for an invoice.

    Status values:
        "not_requested" — no row (WhatsApp was not requested for this invoice)
        "initiated"     — POS handed it to Kodryx, awaiting Kodryx response
        "sent"          — Kodryx accepted the request (2xx)
        "failed"        — Kodryx rejected or unreachable; merchant copy still valid
        "skipped"       — duplicate / already-handled
    """
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT status, response_code, error, updated_at
              FROM kodryx_delivery_log
             WHERE invoice_id = %s;
            """,
            (invoice_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch delivery status: {e}",
        )

    if row is None:
        return {
            "invoice_id": invoice_id,
            "status": "not_requested",
            "response_code": None,
            "error": None,
            "updated_at": None,
        }

    return {
        "invoice_id": invoice_id,
        "status": row[0],
        "response_code": row[1],
        "error": row[2],
        "updated_at": row[3].isoformat() if row[3] else None,
    }
