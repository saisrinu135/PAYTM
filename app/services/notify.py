"""Email notifications.

stdlib smtplib + email.message -- no aiosmtplib, no sendgrid client. smtplib is
blocking, so the one send runs in asyncio.to_thread; that is the entire reason a
library would exist here.

This module currently holds only the transport (send_email) plus the templates.
The queue() / sweep() pair over the `notifications` table lands in phase 5.

Email is OPTIONAL per customer: customers.email is nullable and
customers.notify_email defaults to false, with a CHECK enforcing that
notify_email cannot be set without an address. A customer with no email is
"skipped_no_email", never a failure -- a shop must be able to record khata for
someone who has never given an email address.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Customer, Notification, Store

log = logging.getLogger(__name__)


class EmailNotSent(RuntimeError):
    """Transport failed. The caller records it against the notification row
    and lets the sweeper retry; it never bubbles up into a ledger write."""


@dataclass(frozen=True)
class Rendered:
    subject: str
    body: str


def _money(amount: Decimal, currency: str = "INR") -> str:
    symbol = "₹" if currency == "INR" else f"{currency} "
    return f"{symbol}{Decimal(amount).quantize(Decimal('0.01')):,}"


# ---- templates -----------------------------------------------------------
# Plain text on purpose. These are read on a cheap phone, often on a bad
# connection, and they carry one number that must be unambiguous.

def render(template: str, payload: dict) -> Rendered:
    store = payload["store_name"]
    name = payload["customer_name"]
    currency = payload.get("currency", "INR")

    if template == "khata_entry":
        amount = _money(payload["amount"], currency)
        lines = [
            f"Namaste {name},",
            "",
            f"{amount} was added to your khata at {store} "
            f"on {payload['occurred_on']}.",
        ]
        if payload.get("note"):
            lines.append(f"For: {payload['note']}")
        lines += [
            "",
            f"Outstanding balance: {_money(payload['balance'], currency)}",
            "",
            f"Reply to this mail or speak to {payload['owner_name']} "
            f"if this does not look right.",
        ]
        return Rendered(
            subject=f"{store}: {amount} added to your khata",
            body="\n".join(lines) + "\n",
        )

    if template == "payment_receipt":
        return Rendered(
            subject=f"{store}: payment of {_money(payload['amount'], currency)} received",
            body=(
                f"Namaste {name},\n\n"
                f"We received {_money(payload['amount'], currency)} on "
                f"{payload['occurred_on']}. Thank you.\n\n"
                f"Remaining balance: {_money(payload['balance'], currency)}\n"
            ),
        )

    if template == "due_reminder":
        return Rendered(
            subject=f"{store}: khata balance {_money(payload['balance'], currency)}",
            body=(
                f"Namaste {name},\n\n"
                f"Your khata balance at {store} is "
                f"{_money(payload['balance'], currency)}, unchanged since "
                f"{payload['last_activity']}.\n\n"
                f"Please settle when convenient.\n"
            ),
        )

    raise ValueError(f"unknown template: {template!r}")


# ---- transport -----------------------------------------------------------

def _send_blocking(settings: Settings, to: str, r: Rendered) -> None:
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = r.subject
    msg.set_content(r.body)

    with smtplib.SMTP(
        settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout
    ) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)


async def send_email(settings: Settings, to: str, template: str, payload: dict) -> None:
    """Send one message. Raises EmailNotSent on any transport failure.

    Never logs `to`, the subject, or the body: all three carry a customer's
    name and outstanding balance.
    """
    if not settings.email_enabled:
        log.info("email skipped: no SMTP_HOST configured", extra={"template": template})
        return

    rendered = render(template, payload)
    try:
        await asyncio.to_thread(_send_blocking, settings, to, rendered)
    except (smtplib.SMTPException, OSError) as e:
        # The exception text can contain the recipient address, so log the type
        # only and keep the detail for the notifications.last_error column.
        log.warning(
            "email send failed", extra={"template": template, "error": type(e).__name__}
        )
        raise EmailNotSent(str(e)) from e
    log.info("email sent", extra={"template": template})


# ---- the queue -----------------------------------------------------------
# Postgres IS the queue. No Redis, no arq: a notifications row plus one sweeper
# using FOR UPDATE SKIP LOCKED is correct with multiple uvicorn workers.
# ponytail: move to arq only when real backoff curves are needed.

MAX_ATTEMPTS = 5


async def queue(
    session: AsyncSession,
    *,
    store: Store,
    customer: Customer,
    template: str,
    payload: dict,
) -> Notification:
    """Record the intent to notify. Never sends; never raises on a missing
    address.

    A customer with no email is `skipped_no_email`, not `failed`. That
    distinction matters: a shop must be able to record khata for someone who
    never gave an email, and a queue full of permanent "failures" hides the
    real ones.

    Called inside the same transaction as the ledger write, so a notification
    cannot exist for an entry that rolled back.
    """
    status = "queued" if (customer.email and customer.notify_email) else "skipped_no_email"
    n = Notification(
        store_id=store.id,
        customer_id=customer.id,
        channel="email",
        template=template,
        # Rendering happens at send time from this payload, so a template fix
        # applies to anything still queued.
        payload=payload,
        status=status,
    )
    session.add(n)
    log.info("notification %s", status,
             extra={"template": template, "customer_id": str(customer.id)})
    return n


async def sweep(sessionmaker, settings: Settings, *, limit: int = 20) -> dict[str, int]:
    """Send one batch of queued notifications. Safe to run concurrently.

    SKIP LOCKED is what makes that true: two workers select disjoint rows
    instead of both sending the same email.
    """
    sent = failed = 0
    async with sessionmaker() as session:
        rows = (await session.execute(
            select(Notification)
            .where(Notification.status == "queued",
                   Notification.attempts < MAX_ATTEMPTS)
            .order_by(Notification.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )).scalars().all()

        for n in rows:
            email = await session.scalar(
                select(Customer.email).where(Customer.id == n.customer_id)
            )
            if not email:
                n.status = "skipped_no_email"
                continue
            n.attempts += 1
            try:
                await send_email(settings, email, n.template, n.payload)
            except EmailNotSent as e:
                # Keep the detail here rather than in the log, where it would
                # leak the recipient address.
                n.last_error = str(e)[:500]
                if n.attempts >= MAX_ATTEMPTS:
                    n.status = "failed"
                failed += 1
            else:
                n.status = "sent"
                n.sent_at = datetime.now(UTC)
                n.last_error = None
                sent += 1
        await session.commit()

    if sent or failed:
        log.info("notification sweep done", extra={"sent": sent, "failed": failed})
    return {"sent": sent, "failed": failed, "examined": len(rows)}


async def sweeper_loop(sessionmaker, settings: Settings) -> None:
    """Background task started by the lifespan. Survives its own failures --
    an unhandled exception here would silently stop all notifications."""
    interval = settings.notify_sweep_seconds
    log.info("notification sweeper started", extra={"interval_s": interval})
    while True:
        try:
            await sweep(sessionmaker, settings)
        except asyncio.CancelledError:
            log.info("notification sweeper stopped")
            raise
        except Exception:
            log.exception("notification sweep failed; will retry")
        await asyncio.sleep(interval)
