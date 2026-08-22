"""Send one of each notification template to the configured SMTP host.

With Mailpit running, this proves the whole email path end to end and lets you
eyeball the templates at http://localhost:8025 before a real customer ever
sees one.

    docker compose up -d mail
    python -m scripts.send_test_email
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

from app.config import get_settings
from app.log import ensure_utf8_stdout
from app.services.notify import EmailNotSent, render, send_email

# Mirrors the seeded Ramesh Kumar: khata 1250.00 given, 500.00 paid,
# 340.50 given -> balance 1090.50.
CASES = [
    ("khata_entry", {
        "store_name": "Vasavi Kirana and General Store",
        "owner_name": "Karthikeya",
        "customer_name": "Ramesh Kumar",
        "amount": Decimal("340.50"),
        "balance": Decimal("1090.50"),
        "occurred_on": "16 August 2026",
        "note": "oil + atta",
        "currency": "INR",
    }),
    ("payment_receipt", {
        "store_name": "Vasavi Kirana and General Store",
        "owner_name": "Karthikeya",
        "customer_name": "Fatima Begum",
        "amount": Decimal("800.00"),
        "balance": Decimal("0.00"),
        "occurred_on": "20 August 2026",
        "currency": "INR",
    }),
    ("due_reminder", {
        "store_name": "Vasavi Kirana and General Store",
        "owner_name": "Karthikeya",
        "customer_name": "Murugan S",
        "balance": Decimal("2100.00"),
        "last_activity": "12 July 2026",
        "currency": "INR",
    }),
]

RECIPIENTS = {
    "khata_entry": "ramesh.k@example.test",
    "payment_receipt": "fatima@example.test",
    "due_reminder": "murugan.s@example.test",
}


async def main() -> int:
    ensure_utf8_stdout()
    settings = get_settings()
    if not settings.email_enabled:
        print("SMTP_HOST is empty -- set it in .env (use 'localhost' with Mailpit).")
        return 1

    print(f"sending via {settings.smtp_host}:{settings.smtp_port} "
          f"(starttls={settings.smtp_starttls})\n")

    failed = 0
    for template, payload in CASES:
        r = render(template, payload)
        print(f"--- {template} -> {RECIPIENTS[template]}")
        print(f"    subject: {r.subject}")
        try:
            await send_email(settings, RECIPIENTS[template], template, payload)
            print("    sent")
        except EmailNotSent as e:
            print(f"    FAILED: {e}")
            failed += 1

    if not failed:
        print("\nall sent -- open http://localhost:8025 to read them")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
