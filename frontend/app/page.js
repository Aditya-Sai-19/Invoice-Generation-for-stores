"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Backend API base URL.
 * Make sure your FastAPI server is running on this port.
 */
const API_URL = "http://localhost:8000";

// Mirror of backend `_PHONE_RE` — keep both in sync.
// Allowed: India (+91 + 10-digit mobile starting 6–9) or US (+1 + 10-digit
// number whose area code starts 2–9). Anything else is rejected.
const PHONE_RE = /^(\+91[6-9]\d{9}|\+1[2-9]\d{9})$/;
const PHONE_HELP = "Use +91XXXXXXXXXX (India) or +1XXXXXXXXXX (US).";

// Keystroke-level keys we always allow through the phone field
// (navigation, deletion, copy/paste shortcuts).
const PHONE_CONTROL_KEYS = new Set([
  "Backspace", "Delete", "Tab", "Escape", "Enter",
  "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown",
  "Home", "End",
]);

// Frontend never talks to Kodryx directly; it only polls our own backend
// for the delivery status the backend recorded after handing off to Kodryx.
const DELIVERY_POLL_INTERVAL_MS = 3000;
const DELIVERY_POLL_MAX_ATTEMPTS = 10;

export default function Home() {
  // ═══════════════════════════════════════════════════════════════
  // State Variables
  // ═══════════════════════════════════════════════════════════════

  // Backend connection status
  const [backendStatus, setBackendStatus] = useState("loading"); // "loading" | "online" | "offline"
  const [backendMessage, setBackendMessage] = useState("");

  // Invoice form fields
  const [customerName, setCustomerName] = useState("");
  const [customerPhone, setCustomerPhone] = useState("");
  const [sendViaWhatsapp, setSendViaWhatsapp] = useState(true);
  const [productName, setProductName] = useState("");
  const [quantity, setQuantity] = useState("");
  const [price, setPrice] = useState("");

  // List of products added to the invoice
  const [items, setItems] = useState([]);

  // UI state for loading and notifications
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [toast, setToast] = useState(null); // { type: "success" | "error", message: string }

  // WhatsApp delivery indicator (non-blocking — merchant download is independent)
  const [deliveryStatus, setDeliveryStatus] = useState(null); // see mapDeliveryStatus
  const [currentInvoiceId, setCurrentInvoiceId] = useState(null);
  const pollControlRef = useRef({ aborted: true, timer: null });

  // Phone input — held via ref so we can attach a NATIVE `beforeinput`
  // listener. React's onBeforeInput is a polyfill that doesn't reliably
  // fire for every input path (virtual keyboards, IME, some autofills);
  // the native DOM event always fires and supports preventDefault.
  const phoneInputRef = useRef(null);

  const phoneTrimmed = customerPhone.trim();
  const phoneValid = PHONE_RE.test(phoneTrimmed);
  const phoneHasError = sendViaWhatsapp && phoneTrimmed !== "" && !phoneValid;

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

  // Cancel any in-flight delivery poller when the component unmounts.
  useEffect(() => {
    return () => {
      pollControlRef.current.aborted = true;
      if (pollControlRef.current.timer) {
        clearTimeout(pollControlRef.current.timer);
      }
    };
  }, []);

  // Hard guarantee against alphabetic input. We attach a NATIVE
  // `beforeinput` listener (not React's synthetic one) so the block
  // fires for every text-insertion path the browser supports.
  useEffect(() => {
    const el = phoneInputRef.current;
    if (!el) return;
    const block = (e) => {
      const data = e.data;
      if (data == null) return;
      for (let i = 0; i < data.length; i++) {
        const ch = data[i];
        // Allow digits + the literal "+". onChange dedupes/repositions "+".
        if ((ch >= "0" && ch <= "9") || ch === "+") continue;
        e.preventDefault();
        return;
      }
    };
    el.addEventListener("beforeinput", block);
    return () => el.removeEventListener("beforeinput", block);
  }, []);

  // ═══════════════════════════════════════════════════════════════
  // Delivery status helpers
  // ═══════════════════════════════════════════════════════════════
  function mapDeliveryStatus(apiStatus) {
    // Mirrors backend kodryx_delivery_log.status values.
    switch (apiStatus) {
      case "initiated":
        return { key: "initiated", label: "WhatsApp delivery initiated", tone: "warning" };
      case "sent":
        return { key: "sent", label: "WhatsApp delivery sent", tone: "success" };
      case "failed":
        return { key: "failed", label: "WhatsApp delivery failed", tone: "danger" };
      case "skipped":
        return { key: "skipped", label: "WhatsApp delivery skipped", tone: "muted" };
      case "not_requested":
        return { key: "not_requested", label: "WhatsApp delivery not requested", tone: "muted" };
      default:
        return { key: "initiated", label: "WhatsApp delivery initiated", tone: "warning" };
    }
  }

  async function pollDeliveryStatus(invoiceId) {
    // Cancel any prior poller so a fast second submit can't leak timers.
    pollControlRef.current.aborted = true;
    if (pollControlRef.current.timer) {
      clearTimeout(pollControlRef.current.timer);
    }
    const control = { aborted: false, timer: null };
    pollControlRef.current = control;

    let attempts = 0;
    const terminal = new Set(["sent", "failed", "skipped"]);

    async function tick() {
      if (control.aborted) return;
      attempts += 1;
      try {
        const res = await fetch(
          `${API_URL}/invoice-delivery-status/${invoiceId}`,
        );
        if (!control.aborted && res.ok) {
          const data = await res.json();
          setDeliveryStatus(mapDeliveryStatus(data.status));
          if (terminal.has(data.status)) return;
        }
      } catch {
        // Polling errors are non-fatal — merchant copy is unaffected.
      }
      if (!control.aborted && attempts < DELIVERY_POLL_MAX_ATTEMPTS) {
        control.timer = setTimeout(tick, DELIVERY_POLL_INTERVAL_MS);
      }
    }

    control.timer = setTimeout(tick, DELIVERY_POLL_INTERVAL_MS);
  }

  // ═══════════════════════════════════════════════════════════════
  // Helper: Show a toast notification
  // ═══════════════════════════════════════════════════════════════
  function showToast(type, message) {
    setToast({ type, message });
  }

  // ═══════════════════════════════════════════════════════════════
  // Phone field: hard restriction to digits (with a single leading "+").
  // Keystroke handler blocks disallowed keys before they appear; the
  // change handler also sanitizes any paste / IME / autofill input.
  // Together they guarantee the field can never hold a non-numeric char.
  // ═══════════════════════════════════════════════════════════════
  function handlePhoneKeyDown(e) {
    if (e.ctrlKey || e.metaKey || e.altKey) return;        // copy/paste etc.
    if (PHONE_CONTROL_KEYS.has(e.key)) return;
    // "Unidentified" / "Process" come from IME / virtual keyboards —
    // let them through here; `onBeforeInput` below blocks the actual text.
    if (e.key === "Unidentified" || e.key === "Process") return;
    // Allow "+" only at the very start of the input.
    if (e.key === "+" && e.target.selectionStart === 0) return;
    // Allow digits.
    if (/^\d$/.test(e.key)) return;
    // Anything else (letters, symbols, spaces) is rejected at the keystroke.
    e.preventDefault();
  }

  // Sanitize whatever survives (e.g. programmatic value changes) so the
  // field can never display a non-numeric character.
  function handlePhoneChange(e) {
    let v = e.target.value;
    if (v.startsWith("+")) {
      v = "+" + v.slice(1).replace(/\D/g, "");
    } else {
      v = v.replace(/\D/g, "");
    }
    setCustomerPhone(v);
  }

  function handlePhonePaste(e) {
    // Pre-clean clipboard text before it reaches onChange — this gives
    // a clean digit-only result even when the user pastes "+91 98765 43210".
    e.preventDefault();
    const raw = (e.clipboardData || window.clipboardData)?.getData("text") || "";
    let cleaned = raw.startsWith("+")
      ? "+" + raw.slice(1).replace(/\D/g, "")
      : raw.replace(/\D/g, "");
    // Splice into current value at the cursor position.
    const el = e.target;
    const start = el.selectionStart ?? customerPhone.length;
    const end = el.selectionEnd ?? customerPhone.length;
    const next = customerPhone.slice(0, start) + cleaned + customerPhone.slice(end);
    // Re-sanitize the merged string (in case "+" ended up mid-string).
    const final = next.startsWith("+")
      ? "+" + next.slice(1).replace(/\D/g, "")
      : next.replace(/\D/g, "");
    setCustomerPhone(final);
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

    // Phone is required when WhatsApp delivery is on. Only Indian (+91)
    // and US (+1) mobile numbers are accepted.
    if (sendViaWhatsapp && !phoneValid) {
      showToast("error", PHONE_HELP);
      return;
    }

    // Reset any previous delivery indicator so a new run starts clean.
    pollControlRef.current.aborted = true;
    if (pollControlRef.current.timer) {
      clearTimeout(pollControlRef.current.timer);
    }
    setDeliveryStatus(null);
    setCurrentInvoiceId(null);

    // Show loading state
    setIsSubmitting(true);

    try {
      // Step 1: Send invoice data to the backend
      const res = await fetch(`${API_URL}/generate-invoice`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          customer_name: customerName.trim(),
          customer_phone: sendViaWhatsapp ? phoneTrimmed : null,
          send_via_whatsapp: sendViaWhatsapp,
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

        // Capture the backend-assigned invoice id for delivery polling.
        const invoiceIdHeader = res.headers.get("X-Invoice-Id");
        const invoiceId = invoiceIdHeader ? Number(invoiceIdHeader) : null;
        if (invoiceId) setCurrentInvoiceId(invoiceId);

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

        // Step 6: Surface a non-blocking WhatsApp delivery indicator.
        if (sendViaWhatsapp && phoneTrimmed && invoiceId) {
          setDeliveryStatus({
            key: "initiated",
            label: "WhatsApp delivery initiated",
            tone: "warning",
          });
          pollDeliveryStatus(invoiceId);
        } else {
          setDeliveryStatus({
            key: "generated",
            label: "Invoice generated",
            tone: "muted",
          });
        }

        // Reset the form for the next invoice
        setCustomerName("");
        setCustomerPhone("");
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
        <h1 className="header__logo">POS Invoice Generator</h1>
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
        <div className="card__title">Customer Information</div>
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

        <div className="form-group">
          <label className="form-label" htmlFor="customerPhone">
            Customer Phone {sendViaWhatsapp && <span className="form-label__hint">(required for WhatsApp)</span>}
          </label>
          <input
            id="customerPhone"
            className={`form-input ${phoneHasError ? "form-input--error" : ""}`}
            type="tel"
            inputMode="numeric"
            autoComplete="tel"
            maxLength={13}
            placeholder="+919876543210 or +14155551234"
            pattern="^(\+91[6-9]\d{9}|\+1[2-9]\d{9})$"
            title={PHONE_HELP}
            ref={phoneInputRef}
            value={customerPhone}
            onKeyDown={handlePhoneKeyDown}
            onPaste={handlePhonePaste}
            onChange={handlePhoneChange}
            aria-invalid={phoneHasError}
          />
          {phoneHasError && (
            <p className="form-error">{PHONE_HELP}</p>
          )}
          {!sendViaWhatsapp && (
            <p className="form-hint">Optional — no WhatsApp delivery for this invoice.</p>
          )}
        </div>

        <div className="form-group toggle-row">
          <label className="toggle" htmlFor="sendViaWhatsapp">
            <input
              id="sendViaWhatsapp"
              type="checkbox"
              role="switch"
              checked={sendViaWhatsapp}
              onChange={(e) => setSendViaWhatsapp(e.target.checked)}
            />
            <span className="toggle__track" aria-hidden="true">
              <span className="toggle__thumb" />
            </span>
            <span className="toggle__label">Send invoice via WhatsApp</span>
          </label>
        </div>
      </div>


      {/* ── Add Product Card ────────────────────────────────────── */}
      <div className="card">
        <div className="card__title">Add Products</div>

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
          >
            Add Item
          </button>
        </div>
      </div>



      {/* ── Product List Card ───────────────────────────────────── */}
      <div className="card">
        <div className="card__title">Invoice Items</div>

        {/* Show empty state or product table */}
        {items.length === 0 ? (
          <div className="empty-state">
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
                          ✕
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
            isSubmitting ||
            (sendViaWhatsapp && !phoneValid)
          }
          onClick={handleGenerateInvoice}
        >
          {isSubmitting ? (
            <>
              <span className="spinner" />
              Generating PDF…
            </>
          ) : (
            "Generate Invoice"
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

      {/* ── Delivery Status Indicator (non-blocking) ────────────── */}
      {deliveryStatus && (
        <div
          className={`delivery-status delivery-status--${deliveryStatus.tone}`}
          role="status"
          aria-live="polite"
        >
          <span className="delivery-status__dot" />
          <div className="delivery-status__body">
            <div className="delivery-status__label">
              {deliveryStatus.key === "initiated" && (
                <span className="spinner spinner--inline" />
              )}
              {deliveryStatus.label}
              {currentInvoiceId && (
                <span className="delivery-status__id">
                  &nbsp;· Invoice #{currentInvoiceId}
                </span>
              )}
            </div>
            {deliveryStatus.key === "failed" && (
              <div className="delivery-status__sub">
                Merchant copy is still available locally.
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Footer ──────────────────────────────────────────────── */}
      <footer className="footer">
        POS Invoice Generator &middot; Phase 3 &middot; Next.js + FastAPI +
        Neon PostgreSQL + ReportLab
      </footer>
    </main>
  );
}
