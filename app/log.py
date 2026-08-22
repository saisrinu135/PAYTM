"""Logging setup: stdlib logging + dictConfig, no third-party logger.

The only thing structlog/loguru would add here is JSON formatting, which is
the ~15-line Formatter below.

Correlation is the point of this module: `request_id` and `store_id` live in
contextvars set by the middleware, and ContextFilter stamps them onto every
record. That is what lets one voice turn's ingest, speaker score, STT, tool
calls and DB writes be pulled out of the log as a single trace.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from logging.config import dictConfig
from typing import Any

# Set by app.middleware; read by ContextFilter. Defaults keep records valid
# for anything logged outside a request (startup, the notification sweeper).
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
store_id_var: ContextVar[str] = ContextVar("store_id", default="-")

# Fields LogRecord always carries. Anything else on a record came from
# `extra=` and is treated as structured context worth emitting.
_STANDARD_RECORD_FIELDS = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__
) | {"message", "asctime", "taskName", "request_id", "store_id"}


class ContextFilter(logging.Filter):
    """Stamp the current request_id / store_id onto every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.store_id = store_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line, for prod log shipping."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "store_id": getattr(record, "store_id", "-"),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_FIELDS:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def ensure_utf8_stdout() -> None:
    """Force stdout/stderr to UTF-8.

    Not cosmetic. On Windows the console defaults to cp1252, which cannot
    encode the rupee sign or any Telugu/Tamil/Devanagari text -- so a log line
    carrying an amount or a transcript raises UnicodeEncodeError and takes the
    request down with it. A garbled character is an acceptable outcome; a
    crashed ledger write is not, hence errors="replace".

    Linux containers are already UTF-8, so this is a no-op there.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):  # detached or non-text stream
                pass


def configure_logging(level: str = "INFO", fmt: str = "console") -> None:
    ensure_utf8_stdout()
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"context": {"()": ContextFilter}},
            "formatters": {
                "console": {
                    "format": "%(asctime)s %(levelname)-7s [%(request_id)s] "
                              "%(name)s: %(message)s",
                    "datefmt": "%H:%M:%S",
                },
                "json": {"()": JsonFormatter},
            },
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": "json" if fmt == "json" else "console",
                    "filters": ["context"],
                }
            },
            "root": {"handlers": ["default"], "level": level},
            "loggers": {
                # Our middleware already emits one access line per request;
                # uvicorn's would make it two.
                "uvicorn.access": {"handlers": [], "propagate": False},
                "uvicorn.error": {"level": "INFO"},
                # INFO here echoes every statement, which would put ledger
                # amounts and customer contact details into the log.
                "sqlalchemy.engine": {"level": "WARNING"},
                "httpx2": {"level": "WARNING"},
                "openai": {"level": "WARNING"},
            },
        }
    )


# ---------------------------------------------------------------------------
# What must never be logged, in a money app that handles voice:
#   * bearer tokens / api_token_hash  -> redact the whole Authorization header
#   * raw audio bytes                 -> log audio_uri + duration_ms instead
#   * customer speech transcripts     -> log language + length at INFO;
#                                        full text only at DEBUG (off in prod)
#   * customer email / mobile         -> log customer_id instead
#
# Speaker scores, tool names and pending-action ids ARE logged at INFO --
# those are what you need to debug a misrouted utterance and none are PII.
# ---------------------------------------------------------------------------
REDACTED = "***"


def safe_transcript(text: str | None, *, debug: bool = False) -> str:
    """Render a transcript for logs: content only when explicitly debugging."""
    if not text:
        return "<empty>"
    return text if debug else f"<{len(text)} chars>"
