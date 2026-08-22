"""Store profile and customers. Identity of record is mobile + name."""

from __future__ import annotations

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.db import SessionDep, StoreDep
from app.models import Customer
from app.routers._util import money_json
from app.services import ledger

router = APIRouter(prefix="/v1", tags=["stores"])


class CustomerIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    mobile: str = Field(min_length=8, max_length=16)
    name: str = Field(min_length=1, max_length=200)
    email: str | None = None
    language: str | None = None
    notify_email: bool = False


@router.get("/store")
async def store_profile(store: StoreDep):
    return {
        "id": str(store.id),
        "name": store.name,
        "owner_name": store.owner_name,
        "owner_mobile": store.owner_mobile,
        "owner_language": store.owner_language,
        "currency": store.currency,
        "timezone": store.timezone,
    }


@router.get("/customers")
async def list_or_find_customers(
    session: SessionDep,
    store: StoreDep,
    q: str | None = Query(default=None, description="Name or mobile"),
):
    if q:
        found = await ledger.find_customer(session, store.id, q)
        customers = found
    else:
        customers = list((await session.scalars(
            select(Customer)
            .where(Customer.store_id == store.id)
            .order_by(Customer.name)
        )).all())
    return money_json({
        "customers": [
            {
                "id": str(c.id),
                "name": c.name,
                "mobile": c.mobile,
                "email": c.email,
                "language": c.language,
                "notify_email": c.notify_email,
            }
            for c in customers
        ],
    })


@router.post("/customers", status_code=status.HTTP_201_CREATED)
async def create_customer(
    body: CustomerIn,
    session: SessionDep,
    store: StoreDep,
):
    customer = Customer(
        store_id=store.id,
        mobile=body.mobile,
        name=body.name,
        email=body.email,
        language=body.language,
        notify_email=body.notify_email,
    )
    session.add(customer)
    await session.flush()
    return {
        "id": str(customer.id),
        "name": customer.name,
        "mobile": customer.mobile,
        "email": customer.email,
        "language": customer.language,
        "notify_email": customer.notify_email,
    }
