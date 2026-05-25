"""
Kodryx Social — Transactional Messaging client.

This is the ONLY module in the POS that talks to an external communication
provider. All WhatsApp orchestration (templates, media uploads, retries,
webhooks, delivery tracking) is owned by Kodryx Social — we just hand them
the invoice PDF that ReportLab already produced.

Contract:
    POST {KODRYX_API_URL}/api/transactions/send
    Header: X-API-Key: <KODRYX_API_KEY>
    multipart/form-data:
        file              (the existing invoice PDF, NOT regenerated)
        customer_name
        customer_phone
        reference_number  (= invoice_id, our idempotency key)
        amount

Guarantees:
    - Fire-and-forget: never raises into the caller. Invoice generation
      must succeed regardless of Kodryx availability.
    - Idempotent per invoice_id: dedup'd with both a process-level lock
      and a DB row in `kodryx_delivery_log`.
    - Structured audit log written to `kodryx_delivery_log` for every
      attempt (initiated -> sent | failed).
"""

import asyncio
import logging
import time
from typing import Optional

import httpx
import psycopg

logger = logging.getLogger("kodryx")
if not logger.handlers:
    # uvicorn configures the root logger; keep our messages visible regardless.
    logger.setLevel(logging.INFO)


# Process-level dedup: prevents two concurrent background tasks from racing
# on the same invoice within a single process. Cross-process dedup is handled
# by the kodryx_delivery_log table (PRIMARY KEY on invoice_id).
_in_flight: set[int] = set()


def _mask_phone(phone: Optional[str]) -> str:
    if not phone:
        return "***"
    tail = phone[-4:] if len(phone) >= 4 else phone
    return "***" + tail


def _truncate(text: Optional[str], limit: int = 500) -> Optional[str]:
    if text is None:
        return None
    return text if len(text) <= limit else text[:limit] + "...(truncated)"


# ── Synchronous DB helpers (called via asyncio.to_thread from async caller) ──

def _db_read_status(db_url: str, invoice_id: int) -> Optional[str]:
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM kodryx_delivery_log WHERE invoice_id = %s",
                (invoice_id,),
            )
            row = cur.fetchone()
            return row[0] if row else None


def _db_upsert_initiated(db_url: str, invoice_id: int, customer_phone: str) -> None:
    """Insert a fresh 'initiated' row, or reset a previously failed one.

    The WHERE clause on the UPDATE branch makes the operation a no-op when
    another worker has already moved this invoice to 'initiated' or 'sent',
    preserving idempotency across processes.
    """
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO kodryx_delivery_log
                    (invoice_id, customer_phone, status, attempted_at, updated_at)
                VALUES (%s, %s, 'initiated', NOW(), NOW())
                ON CONFLICT (invoice_id) DO UPDATE
                    SET status = 'initiated',
                        error = NULL,
                        response_code = NULL,
                        response_body = NULL,
                        customer_phone = EXCLUDED.customer_phone,
                        updated_at = NOW()
                    WHERE kodryx_delivery_log.status NOT IN ('initiated', 'sent');
                """,
                (invoice_id, customer_phone),
            )
        conn.commit()


def _db_finalize(
    db_url: str,
    invoice_id: int,
    status: str,
    response_code: Optional[int],
    response_body: Optional[str],
    error: Optional[str],
) -> None:
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE kodryx_delivery_log
                   SET status = %s,
                       response_code = %s,
                       response_body = %s,
                       error = %s,
                       updated_at = NOW()
                 WHERE invoice_id = %s;
                """,
                (status, response_code, response_body, error, invoice_id),
            )
        conn.commit()


# ── Main entrypoint ──────────────────────────────────────────────────────────

async def send_invoice_to_kodryx(
    *,
    invoice_id: int,
    pdf_bytes: bytes,
    customer_name: str,
    customer_phone: str,
    amount: float,
    db_url: str,
    kodryx_url: str,
    kodryx_api_key: str,
) -> dict:
    """Upload the EXISTING invoice PDF to Kodryx for WhatsApp delivery.

    This coroutine NEVER raises — all failures are caught, logged, and
    recorded in `kodryx_delivery_log`. It returns a small result dict for
    observability only; the FastAPI BackgroundTask scheduler ignores it.
    """
    masked = _mask_phone(customer_phone)
    started = time.monotonic()

    # 1) Process-level idempotency lock.
    if invoice_id in _in_flight:
        logger.info(
            "kodryx skip in_flight invoice_id=%s phone=%s", invoice_id, masked
        )
        return {"invoice_id": invoice_id, "status": "skipped", "reason": "in_flight"}

    _in_flight.add(invoice_id)
    try:
        # 2) Cross-process idempotency (DB).
        try:
            existing = await asyncio.to_thread(_db_read_status, db_url, invoice_id)
        except Exception as e:
            logger.warning(
                "kodryx db_status_read_failed invoice_id=%s err=%s",
                invoice_id, repr(e),
            )
            existing = None

        if existing in ("initiated", "sent"):
            logger.info(
                "kodryx skip already=%s invoice_id=%s phone=%s",
                existing, invoice_id, masked,
            )
            return {
                "invoice_id": invoice_id,
                "status": "skipped",
                "reason": f"already_{existing}",
            }

        # 3) Mark as initiated before the request goes out.
        try:
            await asyncio.to_thread(
                _db_upsert_initiated, db_url, invoice_id, customer_phone
            )
        except Exception as e:
            # Audit write failed; we still try to send so the customer gets the
            # message, but the DB record will not exist. Log loudly.
            logger.error(
                "kodryx audit_upsert_failed invoice_id=%s err=%s",
                invoice_id, repr(e),
            )

        # 4) POST multipart to Kodryx.
        endpoint = f"{kodryx_url.rstrip('/')}/api/transactions/send"
        files = {
            "file": (f"invoice_{invoice_id}.pdf", pdf_bytes, "application/pdf"),
        }
        data = {
            "customer_name": customer_name,
            "customer_phone": customer_phone,
            "reference_number": str(invoice_id),
            "amount": f"{amount:.2f}",
        }
        headers = {"X-API-Key": kodryx_api_key}

        status_code: Optional[int] = None
        body_snippet: Optional[str] = None
        final_status: str
        error: Optional[str] = None

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    endpoint, headers=headers, files=files, data=data
                )
            status_code = resp.status_code
            body_snippet = _truncate(resp.text)
            if 200 <= status_code < 300:
                final_status = "sent"
            else:
                final_status = "failed"
                error = f"HTTP {status_code}"
        except httpx.TimeoutException as e:
            final_status = "failed"
            error = f"timeout: {e}"
        except httpx.RequestError as e:
            final_status = "failed"
            error = f"network: {e!r}"
        except Exception as e:
            final_status = "failed"
            error = _truncate(repr(e))

        # 5) Record the outcome.
        try:
            await asyncio.to_thread(
                _db_finalize,
                db_url, invoice_id, final_status, status_code, body_snippet, error,
            )
        except Exception as e:
            logger.error(
                "kodryx audit_finalize_failed invoice_id=%s err=%s",
                invoice_id, repr(e),
            )

        duration_ms = int((time.monotonic() - started) * 1000)
        log_fn = logger.info if final_status == "sent" else logger.warning
        log_fn(
            "kodryx %s invoice_id=%s phone=%s code=%s duration_ms=%s error=%s",
            final_status, invoice_id, masked, status_code, duration_ms, error,
        )

        return {
            "invoice_id": invoice_id,
            "status": final_status,
            "response_code": status_code,
            "error": error,
        }

    finally:
        _in_flight.discard(invoice_id)
