"""One HTTP middleware + the exception handlers.

Deliberately one middleware, not five: request-id, timing and the access log
always fire together on the same boundary, so they are one function.

Auth is NOT here -- it is a dependency (app.db.current_store). Middleware runs
on /healthz and /docs too, cannot cleanly hold a DB session, and is not
overridable in tests. A dependency is all three.
"""

from __future__ import annotations

import logging
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.log import request_id_var, store_id_var

log = logging.getLogger("app.access")
err = logging.getLogger("app.error")

# Constraint name -> (status, message). Turns a DB-level guarantee into a
# useful API response instead of a 500. The idempotency rows are the point:
# a retried voice command must read as "already recorded", not as an error.
_CONSTRAINT_MESSAGES: dict[str, tuple[int, str]] = {
    "uq_ledger_idempotency": (status.HTTP_409_CONFLICT,
                              "This entry was already recorded."),
    "uq_sale_idempotency": (status.HTTP_409_CONFLICT,
                            "This sale was already recorded."),
    "uq_customer_store_mobile": (status.HTTP_409_CONFLICT,
                                 "A customer with this mobile already exists."),
    "ck_mobile_e164": (status.HTTP_422_UNPROCESSABLE_CONTENT,
                       "Mobile must be in E.164 format, e.g. +919812345678."),
    "ck_name_nonblank": (status.HTTP_422_UNPROCESSABLE_CONTENT,
                         "Customer name is required."),
    "ck_email_shape": (status.HTTP_422_UNPROCESSABLE_CONTENT,
                       "Email address is not valid."),
    "ck_notify_needs_email": (status.HTTP_422_UNPROCESSABLE_CONTENT,
                              "Email notifications require an email address."),
    "ck_khata_needs_customer": (status.HTTP_422_UNPROCESSABLE_CONTENT,
                                "A khata sale must name a customer."),
    "ck_amount_positive": (status.HTTP_422_UNPROCESSABLE_CONTENT,
                           "Amount must be greater than zero."),
    # The append-only trigger raises rather than violating a constraint, so it
    # arrives as a DBAPIError, handled separately below.
}


def install(app: FastAPI, settings: Settings) -> None:
    """Wire middleware and handlers onto the app."""

    if settings.cors_origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["x-request-id"],
        )

    @app.middleware("http")
    async def observability(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid4().hex[:12]
        rid_token = request_id_var.set(rid)
        store_token = store_id_var.set("-")
        started = perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # Log with the request context still bound, then let the
            # exception handler below build the response.
            elapsed = (perf_counter() - started) * 1000
            err.exception(
                "%s %s -> unhandled", request.method, request.url.path,
                extra={"elapsed_ms": round(elapsed, 1)},
            )
            request_id_var.reset(rid_token)
            store_id_var.reset(store_token)
            raise
        elapsed = (perf_counter() - started) * 1000
        # /healthz is polled by the compose healthcheck every 10s; logging it
        # at INFO would bury everything else.
        level = logging.DEBUG
        log.log(
            level, "%s %s -> %d", request.method, request.url.path, response.status_code,
            extra={"elapsed_ms": round(elapsed, 1), "status": response.status_code},
        )
        response.headers["x-request-id"] = rid
        request_id_var.reset(rid_token)
        store_id_var.reset(store_token)
        return response

    @app.exception_handler(RequestValidationError)
    async def on_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error": "validation_error",
                "detail": exc.errors(),
                "request_id": request_id_var.get(),
            },
        )

    @app.exception_handler(IntegrityError)
    async def on_integrity_error(_: Request, exc: IntegrityError) -> JSONResponse:
        detail = str(getattr(exc, "orig", exc))
        for name, (code, message) in _CONSTRAINT_MESSAGES.items():
            if name in detail:
                err.warning("constraint %s violated", name)
                return JSONResponse(
                    status_code=code,
                    content={"error": name, "detail": message,
                             "request_id": request_id_var.get()},
                )
        err.exception("unmapped integrity error")
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"error": "conflict",
                     "detail": "The request conflicts with existing data.",
                     "request_id": request_id_var.get()},
        )

    @app.exception_handler(Exception)
    async def on_unhandled(_: Request, exc: Exception) -> JSONResponse:
        # The traceback goes to the log. It never goes to the client.
        err.exception("unhandled: %s", type(exc).__name__)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "internal",
                     "detail": "Something went wrong.",
                     "request_id": request_id_var.get()},
        )
