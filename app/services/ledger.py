"""The khata: customer credits, repayments, balances.

This is the product. Everything here is ordinary SQL over `ledger_entries` --
no model computes a rupee amount.

Two invariants shape every function below:

  * The ledger is append-only. `add_entry` only ever INSERTs; a correction is
    `reverse_entry`, which inserts an offsetting row. The database enforces
    this, so these functions cannot drift from it.
  * Balances are derived. There is no cached balance column to fall out of
    sync -- `balance()` is a SUM over a stored generated column.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Row, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Customer, LedgerEntry, Store
from app.services import notify

log = logging.getLogger(__name__)

# The two things an owner actually says. `direction` encodes which way the
# balance moves; keeping it out of the caller's hands means the sign convention
# lives in exactly one place.
EntryKind = Literal["credit_given", "payment_received"]
_DIRECTION: dict[str, int] = {
    "credit_given": 1,      # customer owes MORE  (udhaar given)
    "payment_received": -1,  # customer owes LESS  (paid back)
}
_TEMPLATE: dict[str, str] = {
    "credit_given": "khata_entry",
    "payment_received": "payment_receipt",
}

ZERO = Decimal("0.00")


def _q(amount: Decimal | int | float | str) -> Decimal:
    """Money to exactly two places. Never accepts a float silently -- a float
    rupee amount is a rounding bug waiting to happen."""
    if isinstance(amount, float):
        raise TypeError("pass money as Decimal or str, never float")
    return Decimal(amount).quantize(Decimal("0.01"))


# ---- reads ---------------------------------------------------------------

async def balance(s: AsyncSession, customer_id: UUID) -> Decimal:
    """What this customer owes. Positive = owes the shop. Negative = the shop
    is holding their money (an advance), which is a real case and needs no
    special handling: the signed sum expresses it directly."""
    total = await s.scalar(
        select(func.coalesce(func.sum(LedgerEntry.signed_amount), 0))
        .where(LedgerEntry.customer_id == customer_id)
    )
    return _q(total or 0)


async def find_customer(
    s: AsyncSession, store_id: UUID, query: str
) -> list[Customer]:
    """By mobile if it looks like one, else a case-insensitive name match.

    Always scoped to store_id. The caller gets it from the authenticated
    session, never from an LLM argument, so no tool can reach another tenant.
    """
    q = query.strip()
    stmt = select(Customer).where(Customer.store_id == store_id)
    if q.startswith("+") or q.replace(" ", "").isdigit():
        digits = "".join(ch for ch in q if ch.isdigit())
        stmt = stmt.where(Customer.mobile.like(f"%{digits[-10:]}"))
    else:
        stmt = stmt.where(func.lower(Customer.name).like(f"%{q.lower()}%"))
    return list((await s.scalars(stmt.order_by(Customer.name).limit(10))).all())


async def get_khata(
    s: AsyncSession, store: Store, customer: Customer, limit: int = 10
) -> dict:
    """One customer's statement: balance plus recent entries, newest first.

    Dates are rendered in the store's timezone, because "16 August" has to mean
    what the shopkeeper's calendar says.
    """
    tz = ZoneInfo(store.timezone)
    rows = (await s.execute(
        select(LedgerEntry)
        .where(LedgerEntry.customer_id == customer.id)
        .order_by(LedgerEntry.occurred_at.desc(), LedgerEntry.created_at.desc())
        .limit(limit)
    )).scalars().all()

    bal = await balance(s, customer.id)
    return {
        "customer": {"name": customer.name, "mobile": customer.mobile},
        "balance": bal,
        "owes_shop": bal > ZERO,
        "entries": [
            {
                "id": str(e.id),
                "on": e.occurred_at.astimezone(tz).date().isoformat(),
                "kind": e.entry_type,
                "amount": _q(e.amount),
                "signed": _q(e.signed_amount),
                "note": e.note,
                "from_sale": e.sale_id is not None,
                "reverses": str(e.reverses_id) if e.reverses_id else None,
            }
            for e in rows
        ],
    }


async def list_outstanding(
    s: AsyncSession,
    store_id: UUID,
    *,
    min_amount: Decimal = ZERO,
    older_than_days: int | None = None,
) -> list[Row]:
    """Who owes what. `older_than_days` filters on last activity, not per-lot
    FIFO aging -- "Murugan hasn't moved in 41 days" is the question a shop
    owner actually asks."""
    bal = func.coalesce(func.sum(LedgerEntry.signed_amount), 0).label("balance")
    last = func.max(LedgerEntry.occurred_at).label("last_activity")
    stmt = (
        select(Customer.id, Customer.name, Customer.mobile, Customer.email, bal, last)
        .outerjoin(LedgerEntry, LedgerEntry.customer_id == Customer.id)
        .where(Customer.store_id == store_id)
        .group_by(Customer.id)
        .having(bal > min_amount)
        .order_by(bal.desc())
    )
    if older_than_days is not None:
        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
        stmt = stmt.having(func.max(LedgerEntry.occurred_at) < cutoff)
    return list((await s.execute(stmt)).all())


# ---- the write ------------------------------------------------------------

async def add_entry(
    s: AsyncSession,
    settings: Settings,
    *,
    store: Store,
    customer: Customer,
    kind: EntryKind,
    amount: Decimal,
    request_id: str,
    note: str | None = None,
    created_via: str = "api",
    occurred_at: datetime | None = None,
    sale_id: UUID | None = None,
    utterance_id: UUID | None = None,
    notify_customer: bool = True,
) -> tuple[LedgerEntry, Decimal]:
    """Record a credit given or a payment received. Returns (entry, new balance).

    `request_id` is the idempotency key, unique per store. A retried voice
    command on a flaky shop connection raises IntegrityError, which the
    middleware turns into a clean 409 -- never a duplicate debt.

    The notification is queued in THIS transaction, so it cannot exist for an
    entry that rolled back, and the customer cannot be told about a credit that
    was never recorded.
    """
    amt = _q(amount)
    if amt <= ZERO:
        raise ValueError("amount must be positive; direction encodes the sign")
    if kind not in _DIRECTION:
        raise ValueError(f"unknown entry kind: {kind!r}")
    if customer.store_id != store.id:
        # Defence in depth. The DB would not catch this: both FKs are valid on
        # their own, so only this check stops a cross-tenant write.
        raise ValueError("customer does not belong to this store")

    when = occurred_at or datetime.now(UTC)
    entry = LedgerEntry(
        store_id=store.id,
        customer_id=customer.id,
        entry_type=kind,
        amount=amt,
        direction=_DIRECTION[kind],
        note=note,
        occurred_at=when,
        sale_id=sale_id,
        utterance_id=utterance_id,
        created_via=created_via,
        request_id=request_id,
    )
    s.add(entry)
    await s.flush()          # surfaces a duplicate request_id here, not at commit

    new_balance = await balance(s, customer.id)

    if notify_customer:
        await notify.queue(
            s,
            store=store,
            customer=customer,
            template=_TEMPLATE[kind],
            payload={
                "store_name": store.name,
                "owner_name": store.owner_name,
                "customer_name": customer.name,
                "amount": str(amt),
                "balance": str(new_balance),
                "occurred_on": when.astimezone(ZoneInfo(store.timezone))
                                   .strftime("%d %B %Y"),
                "note": note,
                "currency": store.currency,
            },
        )

    # Amount and balance are the shop's own business records, not third-party
    # PII, and they are what you need to debug a disputed entry.
    log.info(
        "ledger %s recorded", kind,
        extra={"customer_id": str(customer.id), "amount": str(amt),
               "balance": str(new_balance), "via": created_via},
    )
    return entry, new_balance


async def reverse_entry(
    s: AsyncSession,
    settings: Settings,
    *,
    store: Store,
    entry: LedgerEntry,
    reason: str,
    request_id: str,
    created_via: str = "api",
) -> tuple[LedgerEntry, Decimal]:
    """Undo an entry the only way the ledger allows: a new offsetting row.

    UPDATE and DELETE are refused by a database trigger, so this is not a
    convention that a future refactor can quietly break.
    """
    if entry.store_id != store.id:
        raise ValueError("entry does not belong to this store")
    if entry.reverses_id is not None:
        raise ValueError("cannot reverse a reversal")

    already = await s.scalar(
        select(func.count()).select_from(LedgerEntry)
        .where(LedgerEntry.reverses_id == entry.id)
    )
    if already:
        raise ValueError("entry has already been reversed")

    rev = LedgerEntry(
        store_id=store.id,
        customer_id=entry.customer_id,
        entry_type="reversal",
        amount=_q(entry.amount),
        direction=-entry.direction,
        note=reason,
        occurred_at=datetime.now(UTC),
        reverses_id=entry.id,
        created_via=created_via,
        request_id=request_id,
    )
    s.add(rev)
    await s.flush()
    new_balance = await balance(s, entry.customer_id)
    log.info("ledger entry reversed",
             extra={"reversed_id": str(entry.id), "balance": str(new_balance)})
    return rev, new_balance
