"""Talk to the agent from the terminal.

Keeps the conversation_id between turns, which is what makes the confirmation
step work -- "haan" only means anything if the agent remembers what it proposed.

    python -m scripts.chat                      # uses the seeded store's token
    python -m scripts.chat --token <token>
    python -m scripts.chat --url http://127.0.0.1:8000

Type a line and press enter. `/new` starts a fresh conversation, `/q` quits.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.error
import urllib.request

from sqlalchemy import select

from app.config import get_settings
from app.db import dispose_engine, get_sessionmaker, init_engine
from app.log import ensure_utf8_stdout
from app.models import Store

SUGGESTIONS = [
    "ramesh ka kitna baaki hai?",
    "ramesh ko do sau rupaye ka udhaar likh do, chawal",
    "haan sahi hai",
    "murugan ka khata dikhao",
    "naya customer add karo, naam Suresh, number +919876500001",
]


async def _store_name() -> str:
    """Confirm which shop we're talking to, so a wrong token is obvious."""
    cfg = get_settings()
    init_engine(cfg)
    try:
        async with get_sessionmaker()() as s:
            return await s.scalar(select(Store.name).limit(1)) or "?"
    finally:
        await dispose_engine()


def post(url: str, token: str, text: str, conv: str | None) -> dict:
    body: dict = {"text": text}
    if conv:
        body["conversation_id"] = conv
    req = urllib.request.Request(
        f"{url}/v1/agent/text",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    ensure_utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--token", default=None)
    args = ap.parse_args()

    token = args.token
    if not token:
        print("No --token given. Get one by running:  python -m scripts.token")
        return 1

    try:
        store = asyncio.run(_store_name())
    except Exception:
        store = "?"

    print(f"\n  {store}  ·  {args.url}")
    print("  /new for a fresh conversation, /q to quit\n")
    print("  try:")
    for s in SUGGESTIONS:
        print(f"    {s}")
    print()

    conv: str | None = None
    while True:
        try:
            text = input("you > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not text:
            continue
        if text in ("/q", "/quit", "/exit"):
            return 0
        if text == "/new":
            conv = None
            print("     (new conversation)\n")
            continue

        try:
            d = post(args.url, token, text, conv)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            print(f"     HTTP {e.code}: {detail}\n")
            continue
        except urllib.error.URLError as e:
            print(f"     cannot reach {args.url} -- is uvicorn running? ({e.reason})\n")
            continue

        conv = d["conversation_id"]
        print(f"agent> {d['reply']}")
        used = ", ".join(d["tools_used"]) or "none"
        flag = "  TRUNCATED (hit hop ceiling)" if d.get("truncated") else ""
        print(f"       [tools: {used} · hops: {d['hops']}]{flag}\n")


if __name__ == "__main__":
    sys.exit(main())
