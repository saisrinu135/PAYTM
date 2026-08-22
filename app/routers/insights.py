"""Insights REST: one route per metric. Same functions the agent will call
in-process later -- these handlers do not HTTP to themselves.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status

from app.db import SessionDep, StoreDep
from app.routers._util import money_json
from app.services import insights

router = APIRouter(prefix="/v1/insights", tags=["insights"])

Period = Literal[
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


def _period_kwargs(
    period: Period,
    start: datetime | None,
    end: datetime | None,
) -> dict:
    return {"period": period, "start": start, "end": end}


@router.get("/sales-total")
async def sales_total(
    session: SessionDep,
    store: StoreDep,
    period: Period = Query(default="today"),
    start: datetime | None = None,
    end: datetime | None = None,
):
    try:
        result = await insights.sales_total(
            session, store, **_period_kwargs(period, start, end)
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e)) from e
    return money_json(result)


@router.get("/sales-count")
async def sales_count(
    session: SessionDep,
    store: StoreDep,
    period: Period = Query(default="today"),
    start: datetime | None = None,
    end: datetime | None = None,
):
    try:
        result = await insights.sales_count(
            session, store, **_period_kwargs(period, start, end)
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e)) from e
    return money_json(result)


@router.get("/average-ticket")
async def average_ticket(
    session: SessionDep,
    store: StoreDep,
    period: Period = Query(default="today"),
    start: datetime | None = None,
    end: datetime | None = None,
):
    try:
        result = await insights.average_ticket(
            session, store, **_period_kwargs(period, start, end)
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e)) from e
    return money_json(result)


@router.get("/payment-mix")
async def payment_mix(
    session: SessionDep,
    store: StoreDep,
    period: Period = Query(default="today"),
    start: datetime | None = None,
    end: datetime | None = None,
):
    try:
        result = await insights.payment_mix(
            session, store, **_period_kwargs(period, start, end)
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e)) from e
    return money_json(result)


@router.get("/top-items")
async def top_items(
    session: SessionDep,
    store: StoreDep,
    period: Period = Query(default="today"),
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(default=10, ge=1, le=50),
):
    try:
        result = await insights.top_items(
            session, store, limit=limit, **_period_kwargs(period, start, end)
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e)) from e
    return money_json(result)


@router.get("/compare")
async def compare(
    session: SessionDep,
    store: StoreDep,
    period: Period = Query(default="this_month"),
    start: datetime | None = None,
    end: datetime | None = None,
):
    try:
        result = await insights.compare(
            session, store, **_period_kwargs(period, start, end)
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e)) from e
    return money_json(result)


@router.get("/trend")
async def trend(
    session: SessionDep,
    store: StoreDep,
    period: Period = Query(default="this_month"),
    start: datetime | None = None,
    end: datetime | None = None,
):
    try:
        result = await insights.trend(
            session, store, **_period_kwargs(period, start, end)
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e)) from e
    return money_json(result)


@router.get("/top-customers")
async def top_customers(
    session: SessionDep,
    store: StoreDep,
    period: Period = Query(default="this_month"),
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(default=10, ge=1, le=50),
):
    try:
        result = await insights.top_customers(
            session, store, limit=limit, **_period_kwargs(period, start, end)
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e)) from e
    return money_json(result)
