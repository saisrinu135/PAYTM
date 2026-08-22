"""Engine, session factory, and the request-scoped dependencies.

Auth lives here rather than in middleware: a dependency composes with the
session scope, does not run on /healthz or /docs, and is trivially overridable
in tests via app.dependency_overrides.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings
from app.log import store_id_var
from app.models import Store

log = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine(settings: Settings) -> AsyncEngine:
    """Called once from the lifespan. Idempotent."""
    global _engine, _sessionmaker
    if _engine is None:
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_pre_ping=True,  # a shop's connection drops; don't hand out dead ones
            pool_size=5,
            max_overflow=10,
        )
        _sessionmaker = async_sessionmaker(
            _engine, expire_on_commit=False, autoflush=False
        )
    return _engine


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        raise RuntimeError("init_engine() has not run -- is the lifespan wired up?")
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """One transaction per request. Commits on success, rolls back on any
    exception -- so a half-written ledger entry can never survive an error."""
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def hash_token(token: str) -> str:
    """The API token is 256 bits of `secrets.token_urlsafe` entropy, not a
    human-chosen password, so a single SHA-256 is the right primitive here --
    there is nothing to brute-force and we need an indexed equality lookup.
    Use argon2/bcrypt if these ever become user-chosen."""
    return hashlib.sha256(token.encode()).hexdigest()


async def current_store(
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> Store:
    """Resolve `Authorization: Bearer <token>` to a Store.

    This is the ONLY place store_id enters the system. It is bound to a
    contextvar for log correlation and passed explicitly to every service
    call -- the LLM never supplies it, so no tool can address another
    tenant's data even if the model tries.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    store = await session.scalar(
        select(Store).where(Store.api_token_hash == hash_token(token))
    )
    if store is None:
        # Never echo the token, not even a prefix.
        log.warning("auth rejected: unknown token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    store_id_var.set(str(store.id))
    return store


StoreDep = Annotated[Store, Depends(current_store)]


def settings_dep() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(settings_dep)]
