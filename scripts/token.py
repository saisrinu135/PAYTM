"""Print a fresh API token for a store, without touching its data.

Only the SHA-256 hash of a token is stored, so an existing token cannot be
recovered -- it can only be replaced. This rotates it and prints the new one.

Use this instead of re-running the seed: `python -m seeds.seed` deletes the
store and everything cascading from it, so getting a token that way costs you
the ledger.

    python -m scripts.token                    # the only store, or list them
    python -m scripts.token --mobile +919876543210
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys

from sqlalchemy import select

from app.config import get_settings
from app.db import dispose_engine, get_sessionmaker, hash_token, init_engine
from app.log import ensure_utf8_stdout
from app.models import Store


async def main(mobile: str | None) -> int:
    ensure_utf8_stdout()
    init_engine(get_settings())
    try:
        async with get_sessionmaker()() as s:
            stores = list((await s.scalars(select(Store).order_by(Store.name))).all())
            if not stores:
                print("No stores. Run:  python -m seeds.seed", file=sys.stderr)
                return 1

            if mobile:
                store = next((x for x in stores if x.owner_mobile == mobile), None)
                if store is None:
                    print(f"No store with owner_mobile {mobile}", file=sys.stderr)
                    return 1
            elif len(stores) == 1:
                store = stores[0]
            else:
                print("Several stores -- pick one with --mobile:", file=sys.stderr)
                for x in stores:
                    print(f"  {x.owner_mobile}  {x.name}", file=sys.stderr)
                return 1

            token = secrets.token_urlsafe(32)
            store.api_token_hash = hash_token(token)
            await s.commit()

            print(f"\nstore : {store.name}  ({store.owner_name}, {store.owner_language})")
            print(f"token : {token}")
            print("\nThe previous token is now invalid. Use it as:")
            print(f'  Authorization: Bearer {token}\n')
        return 0
    finally:
        await dispose_engine()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mobile", default=None, help="owner_mobile of the store")
    sys.exit(asyncio.run(main(ap.parse_args().mobile)))
