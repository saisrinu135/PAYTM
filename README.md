# SMB Voice Agent

A voice-first agent for small shop owners. Two jobs, one audio pipeline:

1. **Owner ↔ books** — speak a khata (credit ledger) entry, ask a balance, ask
   for store insights. Voice in, voice out, in the owner's language.
2. **Owner ↔ customer** — a live interpreter when the customer speaks a
   different language. The agent is the bridge, not a participant.

What separates the two is *who is speaking*, so **speaker role is the router** —
not an LLM intent classifier. That is also the security boundary: the
translation path calls no language model at all, so customer speech cannot
reach a tool.

FastAPI · SQLAlchemy 2.0 async · Postgres 16 · Alembic · Sarvam (STT/TTS/translate) ·
any OpenAI-compatible LLM.

---

## Quick start

```bash
cp .env.example .env          # then set POSTGRES_PASSWORD
docker compose up -d db       # builds Dockerfile.postgres (pgvector), port 15432

python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt   # Windows
# source .venv/bin/activate && pip install -r requirements-dev.txt  # Linux/mac

alembic upgrade head
python -m seeds.seed          # prints the store's API token -- save it
uvicorn app.main:app --reload
```

Verify:

```bash
curl localhost:8000/healthz   # {"status":"ok"}          liveness, no I/O
curl localhost:8000/readyz    # {"status":"ready",...}   SELECT 1 against Postgres
```

Everything in a container instead:

```bash
docker compose up --build     # api runs `alembic upgrade head` then uvicorn
```

---

## Environment gotchas

These all cost real time on a fresh machine, so they are written down.

| Symptom | Cause | Fix |
|---|---|---|
| `pip`: *Expected package name at the start of dependency specifier* | `requirements.txt` saved as UTF-16. PowerShell `>` and `Set-Content` default to UTF-16 here. | Keep it UTF-8: `pip freeze \| Out-File -Encoding utf8 requirements.txt` |
| `asyncpg`: *password authentication failed for user "smb"* while `psql` inside the container works | Something else already owns host port 5432 (a native Postgres, and 5433 was a `wslrelay`) so host clients reach the wrong server | Compose publishes **15432**; `DATABASE_URL` must match |
| `ZoneInfoNotFoundError: Asia/Kolkata` | Windows ships no system tz database, and slim Linux images may not either | `tzdata` is a required dependency, already in `requirements.txt` |
| `WS /v1/bridge` fails at handshake | plain `uvicorn` has no WebSocket implementation | `uvicorn[standard]` (already pinned) |
| Any audio upload route raises on startup | FastAPI needs `python-multipart` for `UploadFile` | already pinned |
| Docker build is huge / binaries don't run | `.venv` copied into the image | `.dockerignore` excludes it |
| `import httpx` gives a different client than the SDK uses | `openai` 3.x is built on **httpx2**, not httpx | `import httpx2` in `services/sarvam.py` |

Also: `ffmpeg` must be on PATH (the Docker image installs it). Audio ingest
shells out to it to decode browser webm/opus into 16k mono PCM.

---

## Layout

```
app/
  main.py         app factory, lifespan, /healthz + /readyz
  config.py       pydantic-settings; every env var lives here
  log.py          dictConfig + ContextFilter (request_id, store_id correlation)
  middleware.py   ONE http middleware + the exception handlers
  db.py           engine, session dep, current_store auth dep
  models.py       11 SQLAlchemy models -- source of truth for the schema
  services/       ledger + notify (done) | insights, voice, sarvam (pending)
  routers/        voice, khata, insights, stores
alembic/          env.py reads the URL from app.config, not alembic.ini
seeds/seed.py     one store, 4 customers, 6 sales, 6 ledger entries
scripts/          fetch_models.py -- the two .onnx files
```

**Auth is a dependency, not middleware.** `Depends(current_store)` resolves the
bearer token to a `Store`. Middleware would run on `/healthz` and `/docs`,
cannot cleanly hold a DB session, and is not overridable in tests.

---

## Money invariants

These are enforced in **Postgres**, not in application code, so no future
refactor, admin script, or ad-hoc `psql` session can bypass them.

- **`ledger_entries` is append-only.** A `BEFORE UPDATE OR DELETE` trigger
  raises. A correction is a new `reversal` row with `reverses_id` set. This
  table *is* the audit log. The two operations are treated differently on
  purpose:
  - **`UPDATE` — refused unconditionally, no bypass exists.** This is the
    guarantee that makes a khata trustworthy.
  - **`DELETE` — refused unless the transaction opts in** with
    `SET LOCAL app.allow_ledger_purge = 'on'`. Needed because deleting a store
    cascades to its ledger rows, and because a data-erasure request is a
    legitimate operation. `SET LOCAL` is transaction-scoped so it cannot leak,
    and it is greppable: any code that erases ledger rows says so out loud.
    `seeds/seed.py` is currently the only caller.
- **`signed_amount` is a stored generated column** (`amount * direction`), so a
  balance is one `SUM` and the sign convention cannot drift between the writer
  and the reader.
- **Balances are derived, never stored.** A cached balance that drifts from the
  ledger is worse than a slow one.
- **`UNIQUE (store_id, request_id)`** on `ledger_entries` and `sales`. A retried
  voice command on a flaky shop connection is replay-safe by construction, and
  surfaces as a clean 409 rather than a duplicate debt.
- **Mobile + name are mandatory** in three places: Pydantic, `NOT NULL`, and a
  regex `CHECK`. Every `NOT NULL` column with a default has a *server* default,
  so raw SQL inserts behave identically to ORM ones.
- **No money mutation happens without confirmation.** Mutating tools write a
  `pending_actions` row and return a spoken summary; only an utterance whose
  voiceprint resolved to `owner` can confirm it. STT gets numbers wrong —
  "teen sau chalis" and "teen hazaar chalis" differ by one word and ₹2,700.
- **Every money row carries `utterance_id`**, so a khata dispute is settled by
  replaying the audio that created the entry.

Verified by the seed, which fails loudly if any figure drifts:

```
Ramesh 1090.50 · Fatima 0.00 · Murugan 2100.00 · Anjali 0.00
outstanding 3190.50 · sales 6 rows, gross 4475.50
```

---

## Embeddings — pgvector

We store a 192-dim ECAPA voiceprint per enrolled voice in
`speaker_profiles.embedding`, typed `vector(192)` via pgvector.

**Why the type matters more than the index.** `Vector(192)` rejects a
wrong-sized embedding at write time. The earlier `BYTEA` column accepted any
byte string, so a mismatched model would have scored every comparison as
garbage — silently, forever. Verified: inserting a 256-float embedding now
raises.

**Getting pgvector onto Alpine.** `postgres:16-alpine` does not ship it
(`CREATE EXTENSION vector` fails — no `vector.control`; only `cube` is present,
and it caps at 100 dimensions so it cannot hold a 192-dim vector either). The
`db` service therefore builds `Dockerfile.postgres`: pgvector v0.8.1 compiled
from source **onto the same 16-alpine base**.

That base choice is deliberate, and both halves matter:

- **Not `postgres:17-alpine`.** The existing data directory is a 16.13 cluster.
  Postgres does not upgrade a data directory in place across major versions — 17
  refuses to start on a 16 cluster with *"database files are incompatible with
  server"*.
- **Not `pgvector/pgvector:pg16`.** That image is Debian-based, so pointing it at
  an Alpine data directory is a musl → glibc jump. That changes the libc
  collation provider: Postgres logs a collation version mismatch, and text btree
  indexes built under musl can sort incorrectly, so lookups silently miss rows
  until a `REINDEX DATABASE`.

Building onto the image already in use avoids both. Confirmed in practice: after
the swap the ledger still read ₹3,190.50 with **zero** collation warnings in the
log, no reindex and no dump/restore. (`postgres:16-alpine` does ship the server
headers `make` needs — `build-base git` is enough, and `with_llvm=no` means no
clang/llvm.)

### Two-stage speaker ID, and only one stage has authority

```sql
-- stage 2: nearest opted-in customer WITHIN this store
SELECT customer_id, 1 - (embedding <=> :probe) AS similarity
FROM speaker_profiles
WHERE store_id = :store AND customer_id IS NOT NULL   -- NOT optional
ORDER BY embedding <=> :probe LIMIT 3;
```

1. **ROLE** — compare against this store's owner row (`customer_id IS NULL`).
   Decides owner-vs-customer, which decides whether an utterance can reach a
   tool at all. This is the security boundary.
2. **IDENTITY** — nearest opted-in customer profile. A **suggestion only**.
   `mobile` + `name` remains the identity of record, and the confirmation gate
   speaks the name back before money moves — because a misidentification would
   otherwise put a debt on the wrong person's khata.

**The `store_id` filter is load-bearing, not decorative.** There is a test that
proves an unscoped `ORDER BY embedding <=> :probe` *would* return another
shop's customer. Never write that query without the filter.

### Consent is a database constraint

A customer voiceprint is third-party biometric data, so
`ck_customer_profile_needs_consent` refuses any row with `customer_id` set and
`consent_at` NULL. Enforced in Postgres, not in a code path that can be
forgotten. `uq_owner_per_store` (a partial unique index on
`WHERE customer_id IS NULL`) guarantees exactly one voice can gate tool access.

Enrolment is only ever explicit — `POST /v1/customers/{mobile}/voiceprint` with
consent — never harvested from ordinary shop audio.

The HNSW index (`vector_cosine_ops`) exists for stores holding thousands of
profiles. At shop scale the planner will prefer `ix_profiles_store` plus exact
distance, and that is correct: 0.014 ms over 500 vectors.

---

## Email in dev — Mailpit

`docker compose up -d mail` starts an SMTP catcher: it accepts every message
and delivers none. Read them at **http://localhost:8025**.

```bash
docker compose up -d mail
python -m scripts.send_test_email     # one of each template
```

This matters more than a typical dev-mail setup, because these messages carry a
named customer's outstanding balance — you want to see them before a real
customer does.

Mailpit rather than MailHog: MailHog has had no release since 2020. Mailpit is
the maintained drop-in with the same SMTP-catcher + web-UI model. To switch,
change the `mail` service image to `mailhog/mailhog:v1.0.1` — ports 1025/8025
and the env are identical.

Settings (`.env`): `SMTP_HOST=localhost`, `SMTP_PORT=1025`,
`SMTP_STARTTLS=false`, no user or password. Inside compose, the `api` service
overrides `SMTP_HOST=mail`. `config.py` refuses to start with `ENV=prod` +
`SMTP_USER` set + `SMTP_STARTTLS=false`, so the plaintext concession cannot
follow you to production.

An unset `SMTP_HOST` means notifications are **skipped, not failed** — a shop
with no mail configured must still be able to record khata.

---

## Analytics

One service function per metric, exposed twice: a REST endpoint for clients,
and a tool wrapper the agent calls **in-process** (no self-HTTP).

Periods: `today`, `yesterday`, `this_week`, `last_week`, `this_month`,
`last_month`, `this_year`, `last_year`, `last_7_days`, `last_30_days`, `custom`.

**Period boundaries are computed in the store's timezone**, in Python via
`zoneinfo`, then applied as a plain `>= start AND < end` range. Two reasons:
`occurred_at` is `timestamptz`, so "today" in `Asia/Kolkata` is not the UTC day
(an 11:30 PM IST sale would land on the next UTC date and every daily figure
would be wrong by up to 5.5 hours of trade); and a bare range keeps
`ix_sales_store_time` usable, where wrapping the column in `date_trunc()` would
force a sequential scan.

---

## Status

| phase | scope | state |
|---|---|---|
| 0a | scaffolding, config, logging, middleware, docker, health | **done** |
| 0b | models, migration + trigger, seed | **done** |
| 1a | **khata credits**: `services/ledger.py` (add_entry, balance, get_khata, list_outstanding, reverse_entry) + notification queue + sweeper | **done** |
| 1b | analytics: `services/insights.py` (8 metrics, `period_bounds`) + REST routers | next |
| 2 | tools + agent loop + `POST /v1/agent/text` | |
| 3 | voice in/out: VAD, speaker ID, Sarvam STT/TTS | |
| 3b | pgvector voiceprints (owner + opt-in customers) | **done** |
| 4 | translation bridge: `WS /v1/bridge` + wake word | |
| 5 | email notifications + sweeper | **done** (transport, templates, queue, sweeper) |

Phases 0–1 need no LLM and no speech vendor, which is where money correctness
gets locked down before any AI enters the picture.
