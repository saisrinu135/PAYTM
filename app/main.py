"""FastAPI application factory and lifespan."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app import middleware
from app.config import get_settings
from app.db import dispose_engine, get_sessionmaker, init_engine
from app.log import configure_logging
from app.routers import agent, auth, bridge, insights, khata, stores, voice
from app.services import notify

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_engine(settings)
    log.info(
        "starting up",
        extra={"env": settings.env, "llm_model": settings.llm_model},
    )
    settings.audio_dir.mkdir(parents=True, exist_ok=True)

    # One in-process sweeper drains the notifications table. It uses
    # FOR UPDATE SKIP LOCKED, so running several uvicorn workers is safe --
    # they take disjoint rows rather than double-sending someone's khata email.
    sweeper = asyncio.create_task(
        notify.sweeper_loop(get_sessionmaker(), settings), name="notify-sweeper"
    )
    try:
        yield
    finally:
        sweeper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sweeper
        await dispose_engine()
        log.info("shut down")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    app = FastAPI(
        title="Paytm Vaani",
        version="0.1.0",
        lifespan=lifespan,
        # No interactive docs in prod: the schema names every money-mutating
        # endpoint and there is no reason to publish it.
        docs_url=None if settings.is_prod else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_prod else "/openapi.json",
    )

    middleware.install(app, settings)

    @app.get("/healthz", tags=["ops"])
    async def healthz() -> dict[str, str]:
        """Liveness: no I/O. If the process answers, it is alive."""
        return {"status": "ok"}

    @app.get("/readyz", tags=["ops"])
    async def readyz() -> dict[str, str]:
        """Readiness: can we actually reach Postgres?"""
        async with get_sessionmaker()() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ready", "db": "ok"}

    app.include_router(auth.router)
    app.include_router(stores.router)
    app.include_router(khata.router)
    app.include_router(insights.router)
    app.include_router(agent.router)
    app.include_router(bridge.router)
    app.include_router(voice.router)

    return app


app = create_app()
