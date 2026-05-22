# 🧾 POS Invoice Generator — Simple Full-Stack Project

A beginner-friendly Point-of-Sale invoice generator that creates professional PDF invoices.

| Layer     | Tech                  |
| --------- | --------------------- |
| Frontend  | Next.js (React)       |
| Backend   | Python FastAPI        |
| Database  | Neon PostgreSQL       |
| PDF       | Python ReportLab      |

---

## 📁 Project Structure

```
POS_SYSTEM_SIMPLE/
├── backend/
│   ├── main.py              # FastAPI app (API, DB, PDF generation)
│   ├── requirements.txt     # Python dependencies
│   ├── .env                 # Database connection string (edit this)
│   └── .gitignore
├── frontend/
│   ├── app/
│   │   ├── globals.css      # Global styles (dark glassmorphism theme)
│   │   ├── layout.js        # Root layout
│   │   └── page.js          # Invoice form + PDF download page
│   ├── package.json
│   └── ...
└── README.md                # ← You are here
```

---

## 🚀 Complete Setup Guide

### Step 1: Create Neon Database

1. Go to [https://neon.tech](https://neon.tech) and sign up (free tier available).
2. Click **"New Project"** and create a new project.
3. A database will be created automatically.
4. Copy the **connection string** from the dashboard. It looks like this:
   ```
   postgresql://username:password@ep-xxxxx.region.neon.tech/dbname?sslmode=require
   ```

> **Note:** You do NOT need to create any tables manually. The backend creates the `invoices` table automatically on startup!

---

### Step 2: Add DATABASE_URL

Open the file `backend/.env` and paste your Neon connection string:

```env
DATABASE_URL=postgresql://username:password@ep-xxxxx.region.neon.tech/dbname?sslmode=require
```

Replace `username`, `password`, `ep-xxxxx.region.neon.tech`, and `dbname` with your actual values from Neon.

---

### Step 3: Run the Backend (FastAPI)

Open **Terminal 1** and run:

```bash
# Go to the backend folder
cd backend

# Create a virtual environment (first time only)
python -m venv venv

# Activate the virtual environment
# Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# Windows (CMD):
.\venv\Scripts\activate.bat
# macOS / Linux:
source venv/bin/activate

# Install dependencies (first time only)
pip install -r requirements.txt

# Start the FastAPI server on port 8001
uvicorn main:app --port 8001 --reload
```

You should see:
```
Database connected & invoices table ready!
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8001
```

Visit **http://localhost:8001** — you should see:
```json
{
  "status": "ok",
  "message": "POS Invoice Generator API is running!"
}
```

---

### Step 4: Run the Frontend (Next.js)

Open **Terminal 2** and run:

```bash
# Go to the frontend folder
cd frontend

# Install dependencies (first time only)
npm install

# Start the Next.js dev server
npm run dev
```

The frontend will start at **http://localhost:3000**.

---

### Step 5: Test the Full Project

1. Open **http://localhost:3000** in your browser.
2. You should see the green status badge: **"POS Invoice Generator API is running!"**
3. Enter a **customer name** (e.g., "Sai").
4. Add products:
   - Product: Rice, Qty: 2, Price: 50 → click **Add**
   - Product: Dal, Qty: 1, Price: 80 → click **Add**
5. Check that the **product table** shows both items with correct totals.
6. Check that the **grand total** shows Rs.180.00.
7. Click **"Generate Invoice & Download PDF"**.
8. A PDF file (`invoice_1.pdf`) will automatically download.
9. Open the PDF — it should contain:
   - Title: "POS INVOICE"
   - Invoice ID, customer name, date
   - Product table with all items
   - Grand total at the bottom

---

## 🧾 API Reference

### `GET /`
Health check endpoint.

**Response:**
```json
{
  "status": "ok",
  "message": "POS Invoice Generator API is running!"
}
```

### `POST /generate-invoice`
Create a new invoice, save to database, and return a PDF file.

**Request Body:**
```json
{
  "customer_name": "Sai",
  "items": [
    {
      "product_name": "Rice",
      "quantity": 2,
      "price": 50
    },
    {
      "product_name": "Dal",
      "quantity": 1,
      "price": 80
    }
  ]
}
```

**Success Response (200):** Returns a PDF file download (`invoice_<id>.pdf`)

**Error Responses:**
| Code | When |
|------|------|
| 400  | Empty product list |
| 422  | Invalid quantity (< 1) or price (≤ 0) |
| 500  | Database connection, insert, or PDF generation failure |

---

## ✅ Phase 1 — Basic Setup

- [x] Folder structure (`backend/` + `frontend/`)
- [x] Backend: FastAPI basic setup with health check route `/`
- [x] Backend: CORS configured for `http://localhost:3000`
- [x] Frontend: Next.js project initialized
- [x] Frontend: Beautiful home page with backend status check
- [x] README with setup instructions

## ✅ Phase 2 — Invoice Form + Database

- [x] Invoice form (customer name, products, quantity, price)
- [x] Add/remove products with live total calculation
- [x] API endpoint `POST /generate-invoice`
- [x] Pydantic input validation with error handling
- [x] Neon PostgreSQL database integration (auto-create table)
- [x] Success/error toast notifications
- [x] Beautiful glassmorphism UI with responsive design

## ✅ Phase 3 — PDF Generation + Download

- [x] PDF generation using ReportLab
- [x] Professional PDF layout (title, customer info, product table, grand total)
- [x] PDF returned as downloadable file from API
- [x] Auto-download PDF in browser
- [x] Loading spinner while generating
- [x] Clear code comments throughout
