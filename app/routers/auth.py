"""Shopkeeper login: owner mobile + dummy OTP (dev only).

Does not recover the seed API token. Verify mints an OwnerSession bearer;
curl can keep using the seed token. current_store accepts both.
"""

from __future__ import annotations

import hmac
import logging
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select

from app.db import SessionDep, SettingsDep, StoreDep, hash_token
from app.models import OwnerSession, Store

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/auth", tags=["auth"])


class MobileIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    mobile: str = Field(min_length=8, max_length=16)


class VerifyIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    mobile: str = Field(min_length=8, max_length=16)
    otp: str = Field(min_length=4, max_length=8)


def _store_public(store: Store) -> dict:
    return {
        "id": str(store.id),
        "name": store.name,
        "owner_name": store.owner_name,
        "owner_mobile": store.owner_mobile,
        "owner_language": store.owner_language,
        "currency": store.currency,
        "timezone": store.timezone,
    }


def _otp_ok(got: str, expected: str) -> bool:
    a, b = got.encode(), expected.encode()
    if len(a) != len(b):
        return False
    return hmac.compare_digest(a, b)


@router.post("/otp/request")
async def request_otp(body: MobileIn, settings: SettingsDep, session: SessionDep):
    """Always 200. Wrong numbers look the same as right ones.

    No SMS is sent. In dev the OTP is DEV_LOGIN_OTP from the environment.
    """
    if not settings.otp_login_enabled:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="OTP login is disabled outside development.",
        )
    store = await session.scalar(
        select(Store).where(Store.owner_mobile == body.mobile)
    )
    if store is not None:
        log.info("otp requested", extra={"store_id": str(store.id)})
    return {"sent": True}


@router.post("/otp/verify")
async def verify_otp(body: VerifyIn, settings: SettingsDep, session: SessionDep):
    if not settings.otp_login_enabled:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="OTP login is disabled outside development.",
        )
    store = await session.scalar(
        select(Store).where(Store.owner_mobile == body.mobile)
    )
    if store is None or not _otp_ok(body.otp, settings.dev_login_otp):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Invalid mobile or OTP.",
        )

    token = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(days=settings.session_ttl_days)
    session.add(
        OwnerSession(
            store_id=store.id,
            token_hash=hash_token(token),
            expires_at=expires,
        )
    )
    await session.flush()
    log.info("otp verified", extra={"store_id": str(store.id)})
    return {
        "token": token,
        "expires_at": expires.isoformat(),
        "store": _store_public(store),
    }


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    session: SessionDep,
    store: StoreDep,
    authorization: str | None = Header(default=None),
):
    """Drop this UI session. A seed API token is left alone."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return
    token = authorization.split(" ", 1)[1].strip()
    await session.execute(
        delete(OwnerSession).where(
            OwnerSession.token_hash == hash_token(token),
            OwnerSession.store_id == store.id,
        )
    )
