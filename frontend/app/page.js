"use client";

import { useEffect, useState } from "react";

/**
 * Backend API base URL.
 * Make sure your FastAPI server is running on this port.
 */
const API_URL = "http://localhost:8000";

export default function Home() {
  // ═══════════════════════════════════════════════════════════════
  // State Variables
  // ═══════════════════════════════════════════════════════════════

  // Backend connection status
  const [backendStatus, setBackendStatus] = useState("loading"); // "loading" | "online" | "offline"
  const [backendMessage, setBackendMessage] = useState("");

  // Invoice form fields
  const [customerName, setCustomerName] = useState("");
  const [productName, setProductName] = useState("");
  const [quantity, setQuantity] = useState("");
  const [price, setPrice] = useState("");

  // List of products added to the invoice
  const [items, setItems] = useState([]);

  // UI state for loading and notifications
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [toast, setToast] = useState(null); // { type: "success" | "error", message: string }

  // ═══════════════════════════════════════════════════════════════
  // Check if backend is running (on page load)
  // ═══════════════════════════════════════════════════════════════
  useEffect(() => {
    async function checkBackend() {
      try {
        const res = await fetch(API_URL);
        if (res.ok) {
          const data = await res.json();
          setBackendStatus("online");
          setBackendMessage(data.message || "Connected");
        } else {
          setBackendStatus("offline");
          setBackendMessage("Backend returned an error");
        }
      } catch {
        setBackendStatus("offline");
        setBackendMessage("Cannot reach backend at " + API_URL);
      }
    }
    checkBackend();
  }, []);

  // ═══════════════════════════════════════════════════════════════
  // Auto-dismiss toast notification after 5 seconds
  // ═══════════════════════════════════════════════════════════════
  useEffect(() => {
    if (toast) {
      const timer = setTimeout(() => setToast(null), 5000);
      return () => clearTimeout(timer);
    }
  }, [toast]);

  // ═══════════════════════════════════════════════════════════════
  // Helper: Show a toast notification
  // ═══════════════════════════════════════════════════════════════
  function showToast(type, message) {
    setToast({ type, message });
  }

  // ═══════════════════════════════════════════════════════════════
  // Add a product to the invoice list
  // ═══════════════════════════════════════════════════════════════
  function handleAddProduct() {
    // Validate product name
    if (!productName.trim()) {
      showToast("error", "Please enter a product name.");
      return;
    }

    // Validate quantity (must be a whole number >= 1)
    const qty = parseInt(quantity, 10);
    if (isNaN(qty) || qty < 1) {
      showToast("error", "Quantity must be at least 1.");
      return;
    }

    // Validate price (must be a number > 0)
    const prc = parseFloat(price);
    if (isNaN(prc) || prc <= 0) {
      showToast("error", "Price must be greater than 0.");
      return;
    }

    // Create the new product item
    const newItem = {
      id: Date.now(), // unique key for React list rendering
      product_name: productName.trim(),
      quantity: qty,
      price: prc,
      item_total: Math.round(qty * prc * 100) / 100, // calculate total
    };

    // Add to the list
    setItems([...items, newItem]);

    // Clear input fields for the next product
    setProductName("");
    setQuantity("");
    setPrice("");
  }

  // ═══════════════════════════════════════════════════════════════
  // Remove a product from the invoice list
  // ═══════════════════════════════════════════════════════════════
  function handleRemoveProduct(id) {
    setItems(items.filter((item) => item.id !== id));
  }

  // ═══════════════════════════════════════════════════════════════
  // Calculate grand total from all items
  // ═══════════════════════════════════════════════════════════════
  const grandTotal = items.reduce((sum, item) => sum + item.item_total, 0);

  // ═══════════════════════════════════════════════════════════════
  // Generate Invoice — Send data to backend and download PDF
  // ═══════════════════════════════════════════════════════════════
  async function handleGenerateInvoice() {
    // Validate customer name
    if (!customerName.trim()) {
      showToast("error", "Please enter a customer name.");
      return;
    }

    // Validate at least one product exists
    if (items.length === 0) {
      showToast("error", "Please add at least one product.");
      return;
    }

    // Show loading state
    setIsSubmitting(true);

    try {
      // Step 1: Send invoice data to the backend
      const res = await fetch(`${API_URL}/generate-invoice`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          customer_name: customerName.trim(),
          items: items.map((item) => ({
            product_name: item.product_name,
            quantity: item.quantity,
            price: item.price,
          })),
        }),
      });

      // Step 2: Check if the response is a PDF (success) or JSON (error)
      if (res.ok) {
        // Success — the backend returned a PDF file
        const blob = await res.blob();

        // Step 3: Extract filename from the response headers
        const contentDisposition = res.headers.get("Content-Disposition");
        let filename = "invoice.pdf";
        if (contentDisposition) {
          const match = contentDisposition.match(/filename="?(.+?)"?$/);
          if (match) {
            filename = match[1];
          }
        }

        // Step 4: Create a download link and trigger the download
        const url = window.URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();

        // Step 5: Clean up the temporary link
        document.body.removeChild(link);
        window.URL.revokeObjectURL(url);

        // Show success message
        showToast("success", `Invoice downloaded as ${filename}`);

        // Reset the form for the next invoice
        setCustomerName("");
        setItems([]);
      } else {
        // Error — the backend returned an error message
        const data = await res.json();
        const errorMsg =
          data.detail || data.message || "Failed to create invoice.";
        showToast("error", errorMsg);
      }
    } catch (err) {
      // Network error — backend is not reachable
      showToast("error", "Could not connect to backend. Is the server running?");
    } finally {
      // Hide loading state
      setIsSubmitting(false);
    }
  }

  // ═══════════════════════════════════════════════════════════════
  // Handle Enter key in product input fields
  // ═══════════════════════════════════════════════════════════════
  function handleProductKeyDown(e) {
    if (e.key === "Enter") {
      e.preventDefault();
      handleAddProduct();
    }
  }

  // ═══════════════════════════════════════════════════════════════
  // Render the page
  // ═══════════════════════════════════════════════════════════════
  return (
    <main className="page-wrapper">
      {/* ── Toast Notification (top-right corner) ──────────────── */}
      {toast && (
        <div className={`toast toast--${toast.type}`}>
          <span className="toast__icon">
            {toast.type === "success" ? "✅" : "⚠️"}
          </span>
          <span>{toast.message}</span>
          <button
            className="toast__close"
            onClick={() => setToast(null)}
            aria-label="Close notification"
          >
            ✕
          </button>
        </div>
      )}

      {/* ── Header ──────────────────────────────────────────────── */}
      <header className="header">
        <h1 className="header__logo">🧾 POS Invoice Generator</h1>
        <p className="header__subtitle">
          Create &amp; download professional PDF invoices in seconds
        </p>

        {/* Backend connection status badge */}
        <div
          className={`status-badge ${
            backendStatus === "online"
              ? "status-badge--online"
              : backendStatus === "offline"
              ? "status-badge--offline"
              : "status-badge--loading"
          }`}
        >
          <span className="status-dot" />
          {backendStatus === "loading"
            ? "Checking backend…"
            : backendStatus === "online"
            ? backendMessage
            : "Backend offline"}
        </div>
      </header>

      {/* ── Customer Info Card ──────────────────────────────────── */}
      <div className="card">
        <div className="card__title">👤 Customer Information</div>
        <div className="form-group">
          <label className="form-label" htmlFor="customerName">
            Customer Name
          </label>
          <input
            id="customerName"
            className="form-input"
            type="text"
            placeholder="e.g. Sai Rushi"
            value={customerName}
            onChange={(e) => setCustomerName(e.target.value)}
          />
        </div>
      </div>

      <hr className="section-divider" />

      {/* ── Add Product Card ────────────────────────────────────── */}
      <div className="card">
        <div className="card__title">📦 Add Products</div>

        <div className="product-entry">
          {/* Product name input */}
          <div className="form-group">
            <label className="form-label" htmlFor="productName">
              Product Name
            </label>
            <input
              id="productName"
              className="form-input"
              type="text"
              placeholder="e.g. Rice"
              value={productName}
              onChange={(e) => setProductName(e.target.value)}
              onKeyDown={handleProductKeyDown}
            />
          </div>

          {/* Quantity input */}
          <div className="form-group">
            <label className="form-label" htmlFor="quantity">
              Quantity
            </label>
            <input
              id="quantity"
              className="form-input"
              type="number"
              min="1"
              placeholder="1"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              onKeyDown={handleProductKeyDown}
            />
          </div>

          {/* Price input */}
          <div className="form-group">
            <label className="form-label" htmlFor="price">
              Price (Rs.)
            </label>
            <input
              id="price"
              className="form-input"
              type="number"
              min="0.01"
              step="0.01"
              placeholder="50.00"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              onKeyDown={handleProductKeyDown}
            />
          </div>

          {/* Add button */}
          <button
            className="btn btn--secondary"
            onClick={handleAddProduct}
            title="Add this product to the invoice"
          >
            ➕ Add
          </button>
        </div>
      </div>

      <hr className="section-divider" />

      {/* ── Product List Card ───────────────────────────────────── */}
      <div className="card">
        <div className="card__title">🧾 Invoice Items</div>

        {/* Show empty state or product table */}
        {items.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state__icon">📋</div>
            <p>No products added yet. Use the form above to add items.</p>
          </div>
        ) : (
          <>
            {/* Product table */}
            <div className="invoice-table-wrapper">
              <table className="invoice-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Product</th>
                    <th>Qty</th>
                    <th>Price</th>
                    <th>Total</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item, index) => (
                    <tr key={item.id}>
                      <td style={{ color: "var(--text-muted)" }}>
                        {index + 1}
                      </td>
                      <td>{item.product_name}</td>
                      <td>{item.quantity}</td>
                      <td>Rs.{item.price.toFixed(2)}</td>
                      <td className="col-total">
                        Rs.{item.item_total.toFixed(2)}
                      </td>
                      <td>
                        <button
                          className="btn--danger-sm"
                          onClick={() => handleRemoveProduct(item.id)}
                          title="Remove this item"
                        >
                          🗑️
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Grand Total display */}
            <div className="grand-total">
              <span className="grand-total__label">Grand Total</span>
              <span className="grand-total__amount">
                Rs.{grandTotal.toFixed(2)}
              </span>
            </div>
          </>
        )}
      </div>

      {/* ── Generate Invoice Button ─────────────────────────────── */}
      <div style={{ width: "100%", maxWidth: 620, marginTop: "1.5rem" }}>
        <button
          className="btn btn--success"
          disabled={
            backendStatus !== "online" ||
            items.length === 0 ||
            !customerName.trim() ||
            isSubmitting
          }
          onClick={handleGenerateInvoice}
        >
          {isSubmitting ? (
            <>
              <span className="spinner" />
              Generating PDF…
            </>
          ) : (
            "🧾  Generate Invoice & Download PDF"
          )}
        </button>

        {/* Show hint if backend is offline */}
        {backendStatus === "offline" && (
          <p
            style={{
              textAlign: "center",
              marginTop: "0.75rem",
              fontSize: "0.8rem",
              color: "#ef4444",
            }}
          >
            Start the backend first:{" "}
            <code style={{ color: "#f1f5f9" }}>
              uvicorn main:app --reload
            </code>
          </p>
        )}
      </div>

      {/* ── Footer ──────────────────────────────────────────────── */}
      <footer className="footer">
        POS Invoice Generator &middot; Phase 3 &middot; Next.js + FastAPI +
        Neon PostgreSQL + ReportLab
      </footer>
    </main>
  );
}
