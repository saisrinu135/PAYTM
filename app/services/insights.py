"""Store analytics over `sales` / `sale_items`.

One function per metric. Period boundaries are computed in the store's
timezone in Python, then applied as `occurred_at >= start AND occurred_at < end`
so `ix_sales_store_time` stays usable -- wrapping the column in date_trunc
would force a sequential scan, and "today" in Asia/Kolkata is not the UTC day.

`now` is injectable so the seed's 2026-08-22 clock is a fixture, not a race
against the wall clock.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Customer, Sale, SaleItem, Store

ZERO = Decimal("0.00")

PeriodName = Literal[
    "today",
    "yesterday",
    "this_week",
    "last_week",
    "this_month",
    "last_month",
    "this_year",
    "last_year",
    "last_7_days",
    "last_30_days",
    "custom",
]

PERIODS: tuple[str, ...] = (
    "today",
    "yesterday",
    "this_week",
    "last_week",
    "this_month",
    "last_month",
    "this_year",
    "last_year",
    "last_7_days",
    "last_30_days",
    "custom",
)


def _q(amount: Decimal | int | float | str) -> Decimal:
    if isinstance(amount, float):
        raise TypeError("pass money as Decimal or str, never float")
    return Decimal(amount).quantize(Decimal("0.01"))


def _day(d: datetime, tz: ZoneInfo) -> datetime:
    local = d.astimezone(tz)
    return datetime(local.year, local.month, local.day, tzinfo=tz)


def _month_start(year: int, month: int, tz: ZoneInfo) -> datetime:
    return datetime(year, month, 1, tzinfo=tz)


def _add_month(year: int, month: int) -> tuple[int, int]:
    if month == 12:
        return year + 1, 1
    return year, month + 1


def period_bounds(
    period: str,
    tz: ZoneInfo,
    *,
    now: datetime | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Half-open [start, end) instants in `tz`.

    Week is Monday 00:00 through next Monday 00:00 (ISO). Rolling windows
    (`last_7_days`, `last_30_days`) include today.
    """
    if period not in PERIODS:
        raise ValueError(f"unknown period: {period!r}")

    if period == "custom":
        if start is None or end is None:
            raise ValueError("custom period requires start and end")
        a = start.astimezone(tz)
        b = end.astimezone(tz)
        if b <= a:
            raise ValueError("custom period end must be after start")
        return a, b

    clock = (now or datetime.now(tz)).astimezone(tz)
    today = _day(clock, tz)

    if period == "today":
        return today, today + timedelta(days=1)
    if period == "yesterday":
        return today - timedelta(days=1), today
    if period == "last_7_days":
        return today - timedelta(days=6), today + timedelta(days=1)
    if period == "last_30_days":
        return today - timedelta(days=29), today + timedelta(days=1)
    if period == "this_week":
        monday = today - timedelta(days=today.weekday())
        return monday, monday + timedelta(days=7)
    if period == "last_week":
        monday = today - timedelta(days=today.weekday())
        return monday - timedelta(days=7), monday
    if period == "this_month":
        ny, nm = _add_month(today.year, today.month)
        return _month_start(today.year, today.month, tz), _month_start(ny, nm, tz)
    if period == "last_month":
        if today.month == 1:
            ly, lm = today.year - 1, 12
        else:
            ly, lm = today.year, today.month - 1
        return _month_start(ly, lm, tz), _month_start(today.year, today.month, tz)
    if period == "this_year":
        return (
            datetime(today.year, 1, 1, tzinfo=tz),
            datetime(today.year + 1, 1, 1, tzinfo=tz),
        )
    if period == "last_year":
        return (
            datetime(today.year - 1, 1, 1, tzinfo=tz),
            datetime(today.year, 1, 1, tzinfo=tz),
        )
    raise ValueError(f"unknown period: {period!r}")


def prior_bounds(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    """The window of equal length immediately before `start`."""
    return start - (end - start), start


def _window(
    store: Store,
    period: str,
    *,
    now: datetime | None,
    start: datetime | None,
    end: datetime | None,
) -> tuple[datetime, datetime, ZoneInfo]:
    tz = ZoneInfo(store.timezone)
    t0, t1 = period_bounds(period, tz, now=now, start=start, end=end)
    return t0, t1, tz


def _sale_range(store_id: UUID, start: datetime, end: datetime):
    return (
        Sale.store_id == store_id,
        Sale.occurred_at >= start,
        Sale.occurred_at < end,
    )


def _meta(period: str, start: datetime, end: datetime, currency: str) -> dict:
    return {
        "period": period,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "currency": currency,
    }


async def _totals(
    s: AsyncSession, store_id: UUID, start: datetime, end: datetime
) -> tuple[Decimal, int]:
    row = (await s.execute(
        select(
            func.coalesce(func.sum(Sale.total), 0),
            func.count(),
        ).where(*_sale_range(store_id, start, end))
    )).one()
    return _q(row[0] or 0), int(row[1] or 0)


# ---- the eight metrics ---------------------------------------------------

async def sales_total(
    s: AsyncSession,
    store: Store,
    period: PeriodName,
    *,
    now: datetime | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict:
    t0, t1, _ = _window(store, period, now=now, start=start, end=end)
    total, count = await _totals(s, store.id, t0, t1)
    return {**_meta(period, t0, t1, store.currency), "total": total, "count": count}


async def sales_count(
    s: AsyncSession,
    store: Store,
    period: PeriodName,
    *,
    now: datetime | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict:
    t0, t1, _ = _window(store, period, now=now, start=start, end=end)
    _, count = await _totals(s, store.id, t0, t1)
    return {**_meta(period, t0, t1, store.currency), "count": count}


async def average_ticket(
    s: AsyncSession,
    store: Store,
    period: PeriodName,
    *,
    now: datetime | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict:
    t0, t1, _ = _window(store, period, now=now, start=start, end=end)
    total, count = await _totals(s, store.id, t0, t1)
    avg = _q(total / count) if count else ZERO
    return {
        **_meta(period, t0, t1, store.currency),
        "total": total,
        "count": count,
        "average": avg,
    }


async def payment_mix(
    s: AsyncSession,
    store: Store,
    period: PeriodName,
    *,
    now: datetime | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict:
    t0, t1, _ = _window(store, period, now=now, start=start, end=end)
    rows = (await s.execute(
        select(
            Sale.payment_mode,
            func.coalesce(func.sum(Sale.total), 0),
            func.count(),
        )
        .where(*_sale_range(store.id, t0, t1))
        .group_by(Sale.payment_mode)
        .order_by(func.sum(Sale.total).desc())
    )).all()
    mix = {
        mode: {"total": _q(total or 0), "count": int(n)}
        for mode, total, n in rows
    }
    return {**_meta(period, t0, t1, store.currency), "mix": mix}


async def top_items(
    s: AsyncSession,
    store: Store,
    period: PeriodName,
    *,
    now: datetime | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 10,
) -> dict:
    t0, t1, _ = _window(store, period, now=now, start=start, end=end)
    rows = (await s.execute(
        select(
            func.min(SaleItem.item_name).label("item"),
            func.sum(SaleItem.qty).label("qty"),
            func.sum(SaleItem.line_total).label("total"),
        )
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(*_sale_range(store.id, t0, t1))
        .group_by(func.lower(SaleItem.item_name))
        .order_by(func.sum(SaleItem.line_total).desc())
        .limit(limit)
    )).all()
    items = [
        {
            "item": name,
            "qty": Decimal(qty or 0).quantize(Decimal("0.001")),
            "total": _q(total or 0),
        }
        for name, qty, total in rows
    ]
    return {**_meta(period, t0, t1, store.currency), "items": items}


async def compare(
    s: AsyncSession,
    store: Store,
    period: PeriodName,
    *,
    now: datetime | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict:
    """This window versus the equal-length window immediately before it."""
    t0, t1, _ = _window(store, period, now=now, start=start, end=end)
    p0, p1 = prior_bounds(t0, t1)
    cur_total, cur_n = await _totals(s, store.id, t0, t1)
    prior_total, prior_n = await _totals(s, store.id, p0, p1)
    return {
        **_meta(period, t0, t1, store.currency),
        "current": {"start": t0.isoformat(), "end": t1.isoformat(),
                    "total": cur_total, "count": cur_n},
        "prior": {"start": p0.isoformat(), "end": p1.isoformat(),
                  "total": prior_total, "count": prior_n},
        "delta": _q(cur_total - prior_total),
    }


async def trend(
    s: AsyncSession,
    store: Store,
    period: PeriodName,
    *,
    now: datetime | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict:
    """Per-day totals. Bucketed in Python so the SQL stays a plain range scan."""
    t0, t1, tz = _window(store, period, now=now, start=start, end=end)
    rows = (await s.execute(
        select(Sale.occurred_at, Sale.total)
        .where(*_sale_range(store.id, t0, t1))
        .order_by(Sale.occurred_at)
    )).all()

    buckets: dict[str, list[Decimal | int]] = {}
    day = t0
    while day < t1:
        buckets[day.date().isoformat()] = [ZERO, 0]
        day += timedelta(days=1)

    for occurred_at, total in rows:
        key = occurred_at.astimezone(tz).date().isoformat()
        if key not in buckets:
            continue
        buckets[key][0] = _q(buckets[key][0] + _q(total or 0))
        buckets[key][1] = int(buckets[key][1]) + 1

    days = [
        {"on": on, "total": tot, "count": n}
        for on, (tot, n) in buckets.items()
    ]
    return {**_meta(period, t0, t1, store.currency), "days": days}


async def top_customers(
    s: AsyncSession,
    store: Store,
    period: PeriodName,
    *,
    now: datetime | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 10,
) -> dict:
    """Named customers by sales in the window. Walk-ins are one 'walk-in' row."""
    t0, t1, _ = _window(store, period, now=now, start=start, end=end)
    rows = (await s.execute(
        select(
            Sale.customer_id,
            Customer.name,
            Customer.mobile,
            func.coalesce(func.sum(Sale.total), 0),
            func.count(),
        )
        .outerjoin(Customer, Customer.id == Sale.customer_id)
        .where(*_sale_range(store.id, t0, t1))
        .group_by(Sale.customer_id, Customer.name, Customer.mobile)
        .order_by(func.sum(Sale.total).desc())
        .limit(limit)
    )).all()
    customers = [
        {
            "name": name or "walk-in",
            "mobile": mobile,
            "total": _q(total or 0),
            "count": int(n),
        }
        for _cid, name, mobile, total, n in rows
    ]
    return {**_meta(period, t0, t1, store.currency), "customers": customers}
