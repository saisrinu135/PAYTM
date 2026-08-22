"""Khata REST: credits, repayments, statements, reversals.

Mutations go through `services.ledger`. store_id comes from the bearer token
(`current_store`), never from the body.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.db import SessionDep, SettingsDep, StoreDep
from app.routers._util import customer_by_mobile, entry_for_store, money_json
from app.services import ledger

router = APIRouter(prefix="/v1/khata", tags=["khata"])


class AddEntryIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    mobile: str = Field(min_length=8)
    kind: Literal["credit_given", "payment_received"]
    amount: Decimal
    request_id: str = Field(min_length=1, max_length=200)
    note: str | None = None
    notify_customer: bool = True


class ReverseIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    reason: str = Field(min_length=1, max_length=500)
    request_id: str = Field(min_length=1, max_length=200)


@router.get("/outstanding")
async def outstanding(
    session: SessionDep,
    store: StoreDep,
    min_amount: Decimal = Query(default=Decimal("0.00")),
    older_than_days: int | None = Query(default=None, ge=1),
):
    rows = await ledger.list_outstanding(
        session,
        store.id,
        min_amount=min_amount,
        older_than_days=older_than_days,
    )
    tz = ZoneInfo(store.timezone)
    return money_json({
        "customers": [
            {
                "id": str(r.id),
                "name": r.name,
                "mobile": r.mobile,
                "email": r.email,
                "balance": Decimal(r.balance or 0).quantize(Decimal("0.01")),
                "last_activity": (
                    r.last_activity.astimezone(tz).date().isoformat()
                    if r.last_activity is not None
                    else None
                ),
            }
            for r in rows
        ],
    })


@router.get("/customers/{mobile}")
async def customer_khata(
    mobile: str,
    session: SessionDep,
    store: StoreDep,
    limit: int = Query(default=10, ge=1, le=100),
):
    customer = await customer_by_mobile(session, store, mobile)
    return money_json(await ledger.get_khata(session, store, customer, limit=limit))


@router.post("/entries", status_code=status.HTTP_201_CREATED)
async def add_entry(
    body: AddEntryIn,
    session: SessionDep,
    store: StoreDep,
    settings: SettingsDep,
):
    customer = await customer_by_mobile(session, store, body.mobile)
    try:
        entry, balance = await ledger.add_entry(
            session,
            settings,
            store=store,
            customer=customer,
            kind=body.kind,
            amount=body.amount,
            request_id=body.request_id,
            note=body.note,
            created_via="api",
            notify_customer=body.notify_customer,
        )
    except (ValueError, TypeError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e)) from e
    return money_json({
        "id": str(entry.id),
        "kind": entry.entry_type,
        "amount": entry.amount,
        "balance": balance,
        "customer": {"name": customer.name, "mobile": customer.mobile},
    })


@router.post("/entries/{entry_id}/reverse", status_code=status.HTTP_201_CREATED)
async def reverse(
    entry_id: UUID,
    body: ReverseIn,
    session: SessionDep,
    store: StoreDep,
    settings: SettingsDep,
):
    entry = await entry_for_store(session, store, entry_id)
    try:
        rev, balance = await ledger.reverse_entry(
            session,
            settings,
            store=store,
            entry=entry,
            reason=body.reason,
            request_id=body.request_id,
            created_via="api",
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e)) from e
    return money_json({
        "id": str(rev.id),
        "kind": rev.entry_type,
        "amount": rev.amount,
        "reverses": str(entry.id),
        "balance": balance,
    })
