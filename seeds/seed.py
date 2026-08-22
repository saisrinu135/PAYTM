"""Seed one store with realistic khata and sales data.

Every number here is hand-computed so it doubles as the fixture for the
analytics tests. Reference clock: 2026-08-22, a Saturday, Asia/Kolkata.

    Balances     Ramesh 1090.50 | Fatima 0.00 | Murugan 2100.00 | Anjali 0.00
    Outstanding  3190.50 across 2 debtors
    Sales        today 855.00 | this_month 1195.50 | last_month 3280.00
                 this_year 4475.50 across 6 transactions

Run:  python -m seeds.seed          (idempotent -- clears the store first)
"""

from __future__ import annotations

import asyncio
import secrets
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy import delete, func, select, text

from app.config import get_settings
from app.db import dispose_engine, get_sessionmaker, hash_token, init_engine
from app.log import ensure_utf8_stdout
from app.models import (
    EMBEDDING_DIM,
    Customer,
    LedgerEntry,
    Sale,
    SaleItem,
    SpeakerProfile,
    Store,
)

IST = ZoneInfo("Asia/Kolkata")
D = Decimal


def placeholder_embedding(seed: int) -> list[float]:
    """A deterministic unit vector standing in for a real ECAPA embedding.

    NOT a voiceprint. There is no ECAPA model wired up yet (phase 3), and no
    audio was ever processed to produce this. Its only job is to give the
    nearest-neighbour query, the consent constraint and the tenant-isolation
    test real rows to run against.

    Anything that actually decides "is this the owner?" must use an embedding
    produced from real audio -- these numbers would route every utterance
    wrongly. Deterministic (fixed seed) so seeded scores don't move between runs.
    """
    v = np.random.default_rng(seed).standard_normal(EMBEDDING_DIM)
    return (v / np.linalg.norm(v)).tolist()


def ist(y: int, m: int, d: int, hh: int = 11, mm: int = 0) -> datetime:
    """A wall-clock moment in the shop's own timezone.

    Stored as timestamptz, so Postgres keeps the instant; the analytics layer
    converts period boundaries back into IST. Naive datetimes are banned here
    on purpose -- a 23:30 IST sale belongs to that IST day, not the UTC one.
    """
    return datetime(y, m, d, hh, mm, tzinfo=IST)


# ---- the shop and its owner ---------------------------------------------
STORE = dict(
    name="Vasavi Kirana and General Store",
    owner_name="Karthikeya",
    owner_mobile="+919876543210",
    owner_language="te-IN",
    currency="INR",
    timezone="Asia/Kolkata",
)

# ---- customers: mobile + name mandatory, email optional -----------------
CUSTOMERS = [
    # key,       mobile,          name,           email,                  lang,   notify
    ("ramesh",  "+919812345678", "Ramesh Kumar",  "ramesh.k@gmail.com",   "hi-IN", True),
    ("fatima",  "+919823456789", "Fatima Begum",  None,                   "te-IN", False),
    ("murugan", "+919834567890", "Murugan S",     "murugan.s@outlook.com", "ta-IN", True),
    ("anjali",  "+919845678901", "Anjali Rao",    None,                   "te-IN", False),
]

# ---- sales (the transactions), two months so compare/trend have data ----
# key, when,               mode,    customer, total,     items[(name, qty, unit, price)]
SALES = [
    ("s1", ist(2026, 8, 22, 10, 15), "cash", None, D("245.00"), [
        ("Toor dal 1kg", 1, "kg", D("145.00")),
        ("Sugar 1kg", 1, "kg", D("55.00")),
        ("Tea 250g", 1, "pc", D("45.00")),
    ]),
    ("s2", ist(2026, 8, 22, 18, 40), "upi", "anjali", D("610.00"), [
        ("Sunflower oil 1L", 2, "ltr", D("165.00")),
        ("Basmati rice 5kg", 1, "kg", D("280.00")),
    ]),
    ("s3", ist(2026, 8, 16, 19, 5), "khata", "ramesh", D("340.50"), [
        ("Sunflower oil 1L", 1, "ltr", D("165.00")),
        ("Atta 5kg", 1, "kg", D("175.50")),
    ]),
    ("s4", ist(2026, 7, 5, 12, 0), "cash", None, D("480.00"), [
        ("Basmati rice 5kg", 1, "kg", D("280.00")),
        ("Toor dal 1kg", 1, "kg", D("145.00")),
        ("Sugar 1kg", 1, "kg", D("55.00")),
    ]),
    ("s5", ist(2026, 7, 19, 17, 30), "upi", "ramesh", D("700.00"), [
        ("Sunflower oil 1L", 2, "ltr", D("165.00")),
        ("Basmati rice 5kg", 1, "kg", D("280.00")),
        ("Tea 250g", 2, "pc", D("45.00")),
    ]),
    ("s6", ist(2026, 7, 12, 11, 20), "khata", "murugan", D("2100.00"), [
        ("Sunflower oil 1L", 4, "ltr", D("165.00")),
        ("Basmati rice 5kg", 3, "kg", D("280.00")),
        ("Sugar 1kg", 4, "kg", D("55.00")),
        ("Toor dal 1kg", 2, "kg", D("145.00")),
        ("Tea 250g", 2, "pc", D("45.00")),
    ]),
]

# ---- the khata ledger ---------------------------------------------------
# customer, when,              entry_type,         amount,  dir, note, sale_key
LEDGER = [
    ("ramesh",  ist(2026, 8, 1),  "credit_given",     D("1250.00"), 1,
     "monthly grocery, cash short", None),
    ("ramesh",  ist(2026, 8, 9),  "payment_received", D("500.00"), -1, "UPI", None),
    # A khata sale writes TWO rows: the sale AND this ledger entry, joined by sale_id.
    ("ramesh",  ist(2026, 8, 16, 19, 5), "credit_given", D("340.50"), 1,
     "oil + atta", "s3"),
    ("fatima",  ist(2026, 8, 5),  "credit_given",     D("800.00"), 1,
     "medicines run", None),
    ("fatima",  ist(2026, 8, 20), "payment_received", D("800.00"), -1, "cash, full", None),
    ("murugan", ist(2026, 7, 12, 11, 20), "credit_given", D("2100.00"), 1,
     "festival stock", "s6"),
]

EXPECTED_BALANCES = {
    "Ramesh Kumar": D("1090.50"),
    "Fatima Begum": D("0.00"),
    "Murugan S": D("2100.00"),
    "Anjali Rao": D("0.00"),
}


async def seed() -> None:
    ensure_utf8_stdout()
    init_engine(get_settings())
    async with get_sessionmaker()() as s:
        # Idempotent: drop this store and let ON DELETE CASCADE take its data.
        existing = await s.scalar(
            select(Store).where(Store.owner_mobile == STORE["owner_mobile"])
        )
        if existing:
            # The cascade reaches ledger_entries, which the append-only trigger
            # refuses by default. Opting in explicitly, because that is what
            # this is: a deliberate reset, not a rewrite of someone's debt.
            # SET LOCAL is transaction-scoped, so it cannot leak past the commit.
            await s.execute(text("SET LOCAL app.allow_ledger_purge = 'on'"))
            await s.execute(delete(Store).where(Store.id == existing.id))
            await s.flush()

        token = secrets.token_urlsafe(32)
        store = Store(**STORE, api_token_hash=hash_token(token))
        s.add(store)
        await s.flush()

        customers: dict[str, Customer] = {}
        for key, mobile, name, email, lang, notify in CUSTOMERS:
            c = Customer(
                store_id=store.id, mobile=mobile, name=name, email=email,
                language=lang, notify_email=notify,
            )
            s.add(c)
            customers[key] = c
        await s.flush()

        # ---- voiceprints: the owner, plus ONE opted-in customer ----------
        # The owner row (customer_id = NULL) is what decides owner-vs-customer
        # routing. Murugan is the only customer enrolled, with consent recorded
        # -- Ramesh, Fatima and Anjali get none, which is the normal case for a
        # customer who never opted in. See placeholder_embedding: these are not
        # real voiceprints.
        s.add(SpeakerProfile(
            store_id=store.id, label="owner",
            embedding=placeholder_embedding(1),
            sample_count=3, threshold=0.70,
        ))
        s.add(SpeakerProfile(
            store_id=store.id, customer_id=customers["murugan"].id,
            label="customer",
            embedding=placeholder_embedding(2),
            sample_count=1, threshold=0.65,   # suggestion-only, so looser
            consent_at=ist(2026, 7, 12, 11, 25),
            consent_source="verbal",
        ))
        await s.flush()

        sales: dict[str, Sale] = {}
        for key, when, mode, cust_key, total, items in SALES:
            sale = Sale(
                store_id=store.id,
                customer_id=customers[cust_key].id if cust_key else None,
                total=total, payment_mode=mode, occurred_at=when,
                request_id=f"seed-{key}",
            )
            s.add(sale)
            await s.flush()
            for item_name, qty, unit, price in items:
                s.add(SaleItem(
                    sale_id=sale.id, item_name=item_name, qty=D(qty),
                    unit=unit, unit_price=price,
                ))
            sales[key] = sale
        await s.flush()

        for i, (cust_key, when, etype, amount, direction, note, sale_key) in enumerate(LEDGER):
            s.add(LedgerEntry(
                store_id=store.id,
                customer_id=customers[cust_key].id,
                entry_type=etype, amount=amount, direction=direction,
                note=note, occurred_at=when,
                sale_id=sales[sale_key].id if sale_key else None,
                created_via="api", request_id=f"seed-l{i}",
            ))
        await s.commit()

        # ---- verify against the hand-computed figures -------------------
        rows = (await s.execute(
            select(
                Customer.name,
                func.coalesce(func.sum(LedgerEntry.signed_amount), 0).label("balance"),
            )
            .outerjoin(LedgerEntry, LedgerEntry.customer_id == Customer.id)
            .where(Customer.store_id == store.id)
            .group_by(Customer.name)
        )).all()

        print(f"\nstore: {store.name}  ({store.owner_name}, {store.owner_language})")
        print(f"API token (store it, it is not recoverable):\n  {token}\n")
        print("balances:")
        failures = []
        for name, balance in sorted(rows):
            got = D(balance).quantize(D("0.01"))
            want = EXPECTED_BALANCES[name]
            mark = "ok" if got == want else f"MISMATCH expected {want}"
            print(f"  {name:<16} {got:>10}  {mark}")
            if got != want:
                failures.append((name, got, want))

        total_out = sum(v for v in EXPECTED_BALANCES.values())
        actual_out = await s.scalar(
            select(func.coalesce(func.sum(LedgerEntry.signed_amount), 0))
            .where(LedgerEntry.store_id == store.id)
        )
        print(f"\n  total outstanding {D(actual_out).quantize(D('0.01'))} "
              f"(expected {total_out})")

        n_sales = await s.scalar(
            select(func.count()).select_from(Sale).where(Sale.store_id == store.id)
        )
        gross = await s.scalar(
            select(func.coalesce(func.sum(Sale.total), 0)).where(Sale.store_id == store.id)
        )
        print(f"  sales {n_sales} rows, gross {D(gross).quantize(D('0.01'))} "
              f"(expected 6 rows, 4475.50)")

        if failures:
            raise SystemExit(f"\nseed verification FAILED: {failures}")
        print("\nseed ok")

    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(seed())
