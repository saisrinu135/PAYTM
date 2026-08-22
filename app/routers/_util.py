"""Shared HTTP helpers for /v1 routers."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Customer, LedgerEntry, Store


def money_json(obj: object) -> object:
    """Decimals as strings so a rupee amount never becomes a float in JSON."""
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, dict):
        return {k: money_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [money_json(x) for x in obj]
    return obj


async def customer_by_mobile(
    session: AsyncSession, store: Store, mobile: str
) -> Customer:
    customer = await session.scalar(
        select(Customer).where(
            Customer.store_id == store.id,
            Customer.mobile == mobile.strip(),
        )
    )
    if customer is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="No customer with that mobile at this store.",
        )
    return customer


async def entry_for_store(
    session: AsyncSession, store: Store, entry_id: UUID
) -> LedgerEntry:
    entry = await session.scalar(
        select(LedgerEntry).where(
            LedgerEntry.id == entry_id,
            LedgerEntry.store_id == store.id,
        )
    )
    if entry is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="No ledger entry with that id at this store.",
        )
    return entry
