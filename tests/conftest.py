"""Shared test setup.

Tests run against a real Postgres, because the guarantees being tested are
Postgres guarantees: the append-only trigger, the CHECK constraints, the
generated columns and the pgvector dimension check do not exist in a fake.

Prerequisites:
    docker compose up -d db
    alembic upgrade head
    python -m seeds.seed
"""

from __future__ import annotations

import pytest_asyncio

from app.config import Settings, get_settings
from app.db import dispose_engine, get_sessionmaker, init_engine
from app.log import configure_logging


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _engine():
    """One engine for the whole session, disposed cleanly at the end.

    Without the explicit dispose, teardown raises "Event loop is closed" from
    asyncpg trying to cancel on a loop pytest has already torn down -- noisy,
    and it masks real failures in the summary.
    """
    settings = get_settings()
    configure_logging("WARNING", "console")
    init_engine(settings)
    yield
    await dispose_engine()


@pytest_asyncio.fixture(scope="session")
async def settings() -> Settings:
    return get_settings()


@pytest_asyncio.fixture(scope="session")
async def sm():
    return get_sessionmaker()
