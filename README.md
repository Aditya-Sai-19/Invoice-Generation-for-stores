# Kodryx POS — Invoice Generator

A small, branded Point-of-Sale system that takes line items, persists the
invoice, returns a polished PDF, and (optionally) hands the **same** PDF
off to **Kodryx Social** for WhatsApp delivery.

| Layer    | Tech                                              |
| -------- | ------------------------------------------------- |
| Frontend | Next.js 16 (App Router) + React 19                |
| Backend  | Python FastAPI + Pydantic v2                      |
| Database | Neon PostgreSQL (auto-bootstrapped on startup)    |
| PDF      | ReportLab 4 (in-memory, no disk writes)           |
| Delivery | Kodryx Social — `POST /api/transactions/send`     |

---

## Project Structure

```
POS_SYSTEM_SIMPLE/
├── backend/
│   ├── main.py                       # FastAPI app: routes, models, DB
│   ├── services/
│   │   ├── pdf_generator.py          # PDF layout + branding config
│   │   └── kodryx_client.py          # WhatsApp delivery (Kodryx)
│   ├── assets/
│   │   └── logo.png  (or .jpg/.jpeg/.webp)   # your company logo
│   ├── requirements.txt
│   └── .env                          # connection strings + branding
├── frontend/
│   ├── app/
│   │   ├── page.js                   # invoice form (client component)
│   │   ├── layout.js
│   │   └── globals.css               # dark glassmorphism theme
│   └── package.json
└── README.md
```

---

## Setup

### 1. Neon database

Sign up at [https://neon.tech](https://neon.tech), create a project, copy
the connection string. The backend creates the `pos_invoices` and
`kodryx_delivery_log` tables automatically on startup.

### 2. `backend/.env`

```env
# --- Database (required) -----------------------------------------
DATABASE_URL=postgresql://user:pass@ep-xxxx.region.neon.tech/db?sslmode=require

# --- Kodryx WhatsApp delivery (optional; PDF still generates without) ---
KODRYX_API_URL=https://kodryx-social.example.com
KODRYX_API_KEY=your-kodryx-key

# --- Branding shown on the PDF (all optional) --------------------
COMPANY_NAME=KODRYX AI Pvt Ltd
COMPANY_ADDRESS=24, Banjara Hills, Hyderabad 500034
COMPANY_PHONE=+91 98765 43210
COMPANY_EMAIL=contact@kodryx.ai
COMPANY_GST=36AAACA1234B1Z5
COMPANY_WEBSITE=kodryx.ai
COMPANY_TAGLINE=Powered by Kodryx
# Defaults to assets/logo.png; auto-falls back to .jpg/.jpeg/.webp siblings.
# COMPANY_LOGO_PATH=assets/logo.png
```

> **Edit `.env`? You must restart uvicorn.** `--reload` watches `.py`
> files, not `.env`, so env changes don't propagate without a restart.

### 3. Logo

Drop a single file into `backend/assets/`. The PDF renderer auto-discovers
`logo.png` → `logo.jpg` → `logo.jpeg` → `logo.webp` and embeds the first
one it finds. PNG with a transparent background is recommended. Missing
logo? No problem — the layout degrades gracefully.

### 4. Run the backend

```bash
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1        # PowerShell  (Windows)
# source venv/bin/activate         # macOS / Linux
pip install -r requirements.txt
uvicorn main:app --port 8000 --reload
```

Health check at <http://localhost:8000>:

```json
{ "status": "ok", "message": "POS Invoice Generator API is running!" }
```

### 5. Run the frontend

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000>. The status badge turns green when the
backend health check succeeds.

---

## Using the app

1. Enter a **customer name**.
2. Enter the **customer phone** (digits-only field — see "Phone rules" below).
3. Toggle **"Send invoice via WhatsApp"** if you want Kodryx delivery
   (otherwise just the PDF download).
4. Add products (name + qty + price), then **Generate Invoice**.
5. The PDF downloads immediately. If WhatsApp delivery was requested, a
   status indicator polls the backend until Kodryx returns `sent` or
   `failed`. **Merchant download is independent** — even if WhatsApp
   delivery fails, the local PDF is unaffected.

### Phone rules

The phone field accepts **only Indian (+91) or US (+1) mobile numbers**:

* India: `+91XXXXXXXXXX` (first digit 6–9)
* US:    `+1XXXXXXXXXX`  (area code starts 2–9)

Alphabets and symbols are **blocked at the keystroke** via a native
`beforeinput` listener (page.js:115) — they cannot appear in the field
under any input path (physical keys, virtual keyboards, IME, autofill,
paste). The same regex is enforced server-side in
`InvoiceRequest.normalize_phone` (`main.py:108`).

---

## PDF layout

The first page is engineered for clean printing **and** for reliable
WhatsApp thumbnail rendering:

```
┌────────────────────────────────────────────────┐
│ [LOGO]                          BILLING INVOICE│
│ KODRYX AI Pvt Ltd               Invoice #: INV-23
│ 24, Banjara Hills, ...          Date: 25 May 2026, 02:15 PM
│ +91 98765 43210 · contact@kodryx.ai             │
│ GST: 36AAACA1234B1Z5                            │
│ ───────────────────────────────────────────────│
│ BILL TO                                         │
│ Krishna Reddy                                   │
│ +919876543210                                   │
│                                                 │
│ ┌─┬──────────┬───┬───────┬──────────┐           │
│ │#│ Item     │Qty│ Price │ Subtotal │           │
│ └─┴──────────┴───┴───────┴──────────┘           │
│                       ┌───────────────────┐     │
│                       │ Subtotal    x.xx  │     │
│                       │ Tax         0.00  │     │
│                       │ GRAND TOTAL x.xx  │     │
│                       └───────────────────┘     │
│ ───────────────────────────────────────────────│
│        Thank you for your purchase              │
│        Powered by Kodryx                        │
└────────────────────────────────────────────────┘
```

PDF metadata embedded on every render:
`Title="Invoice INV-{id}"`, `Author="Kodryx POS"`,
`Subject="Transactional Invoice"`, `Creator="Kodryx POS System"`.

Tax row is a `0.00` placeholder so the layout is ready for future
taxation — current `grand_total` math is unchanged.

---

## API Reference

### `GET /`
Health check.

### `POST /generate-invoice`

Creates an invoice, persists it, generates the PDF, schedules a
fire-and-forget Kodryx upload, and returns the PDF.

```json
{
  "customer_name": "Krishna Reddy",
  "customer_phone": "+919876543210",
  "send_via_whatsapp": true,
  "items": [
    { "product_name": "Basmati Rice 5kg", "quantity": 2, "price": 550 },
    { "product_name": "Toor Dal 1kg",     "quantity": 3, "price": 165.5 }
  ]
}
```

Response: `application/pdf` with headers:

* `Content-Disposition: attachment; filename="invoice_<id>.pdf"`
* `X-Invoice-Id: <id>` — used by the frontend to poll delivery status

| Code | When |
|------|------|
| 400  | empty product list |
| 422  | invalid phone, qty &lt; 1, price ≤ 0, missing required field |
| 500  | database or PDF failure |

### `GET /invoice-delivery-status/{invoice_id}`

Returns the latest Kodryx delivery state for an invoice:

| Status          | Meaning |
|-----------------|---------|
| `not_requested` | WhatsApp delivery wasn't requested |
| `initiated`     | Backend handed off to Kodryx, awaiting response |
| `sent`          | Kodryx accepted (2xx) |
| `failed`        | Kodryx rejected or unreachable |
| `skipped`       | Duplicate / already handled |

---

## Database

Both tables are auto-created on uvicorn startup (`main.py:188`).

```sql
pos_invoices (
  id SERIAL PK,
  customer_name VARCHAR(100),
  customer_phone VARCHAR(20),
  items JSONB,
  total_amount NUMERIC,
  created_at TIMESTAMP DEFAULT NOW()
)

kodryx_delivery_log (
  invoice_id INT PK,                 -- cross-process idempotency key
  customer_phone VARCHAR(20),
  status VARCHAR(20),                -- initiated | sent | failed | skipped
  response_code INT,
  response_body TEXT,                -- truncated to 500 chars
  error TEXT,
  attempted_at, updated_at TIMESTAMP
)
```

---

## Design notes

* **PDF bytes are generated once and reused** for both the HTTP response
  and the Kodryx upload — no regeneration, no disk writes.
* **POS owns billing + PDF only.** All WhatsApp orchestration (templates,
  retries, webhooks) lives in Kodryx; this codebase has zero Meta /
  WhatsApp API knowledge.
* **Two-layer idempotency for delivery:** an in-process `_in_flight` set
  plus a DB row in `kodryx_delivery_log` keyed by `invoice_id`. Existing
  `initiated`/`sent` rows short-circuit retries.
* **Branding is centralized** in `COMPANY_CONFIG` (`services/pdf_generator.py:44`)
  and driven entirely by env vars — change `.env` and restart uvicorn,
  no code edits required.
