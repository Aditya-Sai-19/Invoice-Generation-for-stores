# Frontend — Kodryx POS

Single-page Next.js 16 App Router client for the Kodryx POS invoice
generator. One client component (`app/page.js`) handles the entire
invoice flow: customer info, item entry, PDF download, and live polling
of WhatsApp delivery status.

For the full project overview and setup, see the [root README](../README.md).

## Stack

- **Next.js 16** (App Router, Turbopack dev server)
- **React 19**
- No UI library — plain React with custom CSS (`app/globals.css`,
  dark glassmorphism theme)

## Run

```bash
npm install
npm run dev          # http://localhost:3000
```

The backend is expected at <http://localhost:8000> (constant `API_URL`
in `app/page.js:9` — update if your uvicorn port differs).

## Files

| File             | Purpose |
|------------------|---------|
| `app/page.js`    | Entire invoice UI + form validation + delivery polling |
| `app/layout.js`  | Root layout + metadata |
| `app/globals.css`| Styling (cards, toggle, toast, delivery-status chip) |

## What `page.js` does

- **Backend health check** on mount — drives the green/red status badge.
- **Customer info** — name + phone + WhatsApp toggle.
- **Phone field hard-restricted to digits**: a native DOM
  `beforeinput` listener attached via `useRef` + `useEffect`
  (page.js:115) blocks every non-digit at the keystroke. Layered with
  `onKeyDown`, `onPaste`, and `onChange` sanitizers so alphabets can
  never appear in the field — regardless of physical/virtual keyboard,
  IME, autofill, or paste.
- **Phone validation regex** mirrors the backend exactly
  (`/^(\+91[6-9]\d{9}|\+1[2-9]\d{9})$/`) — India and US only.
- **Item entry** with add / remove / live grand-total.
- **PDF download** via `POST /generate-invoice`. Reads `X-Invoice-Id`
  from the response headers.
- **Delivery polling** — `GET /invoice-delivery-status/{id}` every 3 s
  up to 10 times, cancel-safe via `pollControlRef` so a fast second
  submit can't leak timers.

## Notes

- The frontend never talks to Kodryx or any WhatsApp API directly — it
  only polls the backend for the status the backend recorded after its
  own fire-and-forget call to Kodryx.
- Merchant PDF download is independent of WhatsApp delivery — if Kodryx
  fails, the local PDF is still fine; only the status chip turns red.
- Phone regex on this side and the backend's `_PHONE_RE`
  (`main.py:42`) **must stay in sync**. Both files have a comment
  reminding you.
