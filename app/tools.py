"""The agent's tools: five of them, all over `services/ledger.py`.

Two rules shape this module.

**`store_id` is never a tool parameter.** It travels in `ToolContext`, built from
the authenticated session. The model cannot name a store, so no tool call can
reach another tenant's khata even if the model tries to.

**Tool definitions carry no `strict: true`.** `openai.pydantic_function_tool()`
forces it, and xAI Grok, Sarvam-M and most non-OpenAI endpoints reject it. Built
by hand from `model_json_schema()` instead, which keeps every provider reachable
by changing `LLM_BASE_URL` alone.

Argument models are deliberately flat -- no nested models -- so
`model_json_schema()` emits no `$defs`/`$ref`, which some providers mishandle.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Customer, PendingAction, Store
from app.services import ledger

log = logging.getLogger(__name__)

GATE_TTL = timedelta(minutes=5)


@dataclass
class ToolContext:
    """Everything a tool needs that the model must not supply."""
    session: AsyncSession
    store: Store
    settings: Settings
    conversation_id: UUID
    # Only an utterance whose voiceprint resolved to `owner` may confirm money.
    # Text requests are owner-authenticated by bearer token, so this is True
    # there; the voice path will set it from the speaker-ID stage.
    speaker_is_owner: bool = True


# ---- argument models -----------------------------------------------------
# The docstring becomes the tool description the model reads, so it is written
# for the model, not for us.

class FindCustomerArgs(BaseModel):
    """Look up a customer of this shop by mobile number or by name. Use this
    before recording anything against a customer, to get their exact mobile
    number. Returns every match, so if more than one comes back, ask the owner
    which person they mean."""
    query: str = Field(description="A mobile number, or part of a name, e.g. 'Ramesh'")


class CreateCustomerArgs(BaseModel):
    """Register a new customer for this shop. Both mobile and name are
    required: the mobile number is how a customer is identified, so never
    invent one -- if the owner has not said it, ask for it first. Email is
    optional and is used only to send the customer a notification when their
    khata changes."""
    mobile: str = Field(description="Mobile in international form, e.g. +919812345678")
    name: str = Field(description="The customer's name as the owner says it")
    email: str | None = Field(default=None, description="Optional email")
    language: str | None = Field(
        default=None, description="Preferred language tag, e.g. ta-IN"
    )


class GetKhataArgs(BaseModel):
    """Read a customer's khata: what they currently owe, and their recent
    credit and payment entries."""
    customer_mobile: str = Field(description="Mobile in international form")
    limit: int = Field(default=5, ge=1, le=25,
                       description="How many recent entries to return")


class AddKhataEntryArgs(BaseModel):
    """Record credit given to a customer (udhaar), or a payment received from
    them. This does NOT save anything yet: it returns a summary that you must
    read back to the owner for confirmation. Only after the owner agrees do you
    call confirm_pending."""
    customer_mobile: str = Field(description="Mobile in international form")
    kind: Literal["credit_given", "payment_received"] = Field(
        description="credit_given when the customer takes goods on credit; "
                    "payment_received when they pay money back"
    )
    amount: Decimal = Field(description="Rupee amount, always positive, e.g. 340.50")
    note: str | None = Field(default=None, description="What it was for, e.g. 'oil and atta'")

    @field_validator("amount")
    @classmethod
    def _positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("amount must be greater than zero")
        return v


class ConfirmPendingArgs(BaseModel):
    """Commit or cancel an entry that add_khata_entry proposed. Call this only
    after the owner has heard the summary and answered. Pass confirm=true if
    they agreed, confirm=false if they did not."""
    pending_id: str = Field(description="The pending_id from add_khata_entry")
    confirm: bool = Field(description="true to save it, false to discard it")


# ---- handlers ------------------------------------------------------------

async def _customer_by_mobile(ctx: ToolContext, mobile: str) -> Customer | None:
    return await ctx.session.scalar(
        select(Customer).where(
            Customer.store_id == ctx.store.id,      # tenant scope, always
            Customer.mobile == mobile.strip(),
        )
    )


async def find_customer(ctx: ToolContext, a: FindCustomerArgs) -> dict:
    matches = await ledger.find_customer(ctx.session, ctx.store.id, a.query)
    out = []
    for c in matches:
        out.append({
            "name": c.name,
            "mobile": c.mobile,
            "balance": str(await ledger.balance(ctx.session, c.id)),
            "has_email": bool(c.email),
        })
    return {"match_count": len(out), "customers": out} if out else {
        "match_count": 0,
        "customers": [],
        "hint": "No customer matched. Ask the owner for the mobile number and "
                "name, then call create_customer.",
    }


async def create_customer(ctx: ToolContext, a: CreateCustomerArgs) -> dict:
    existing = await _customer_by_mobile(ctx, a.mobile)
    if existing:
        return {"created": False, "reason": "already_exists",
                "name": existing.name, "mobile": existing.mobile}
    c = Customer(
        store_id=ctx.store.id,
        mobile=a.mobile.strip(),
        name=a.name.strip(),
        email=a.email,
        language=a.language,
        notify_email=bool(a.email),
    )
    ctx.session.add(c)
    # Surfaces the E.164 / non-blank-name CHECKs here, as a tool error the
    # model can recover from, rather than as a 500 at commit time.
    await ctx.session.flush()
    return {"created": True, "name": c.name, "mobile": c.mobile,
            "will_be_notified": c.notify_email}


async def get_khata(ctx: ToolContext, a: GetKhataArgs) -> dict:
    c = await _customer_by_mobile(ctx, a.customer_mobile)
    if not c:
        return {"error": "no_such_customer",
                "hint": "Call find_customer first to get the exact mobile."}
    k = await ledger.get_khata(ctx.session, ctx.store, c, limit=a.limit)
    return {
        "name": k["customer"]["name"],
        "mobile": k["customer"]["mobile"],
        "balance": str(k["balance"]),
        "owes_shop": k["owes_shop"],
        "entries": [
            {"on": e["on"], "kind": e["kind"], "amount": str(e["amount"]),
             "note": e["note"]}
            for e in k["entries"]
        ],
    }


async def add_khata_entry(ctx: ToolContext, a: AddKhataEntryArgs) -> dict:
    """Writes an INTENT, never a ledger row. See the gate rationale below."""
    c = await _customer_by_mobile(ctx, a.customer_mobile)
    if not c:
        return {"error": "no_such_customer",
                "hint": "Call find_customer first to get the exact mobile."}

    amount = a.amount.quantize(Decimal("0.01"))
    current = await ledger.balance(ctx.session, c.id)
    verb = "credit" if a.kind == "credit_given" else "payment"
    summary = (
        f"{verb} of {amount} for {c.name}"
        + (f", for {a.note}" if a.note else "")
        + f". Their balance is currently {current}."
    )

    pending = PendingAction(
        store_id=ctx.store.id,
        conversation_id=ctx.conversation_id,
        tool_name="add_khata_entry",
        args={
            "customer_mobile": c.mobile,
            "kind": a.kind,
            "amount": str(amount),
            "note": a.note,
        },
        spoken_summary=summary,
        status="awaiting",
        expires_at=datetime.now(UTC) + GATE_TTL,
    )
    ctx.session.add(pending)
    await ctx.session.flush()

    log.info("gate: entry proposed", extra={
        "pending_id": str(pending.id), "customer_id": str(c.id),
        "amount": str(amount), "kind": a.kind,
    })
    return {
        "status": "needs_confirmation",
        "pending_id": str(pending.id),
        "spoken_summary": summary,
        "instruction": "Read this back to the owner in their language and ask "
                       "if it is correct. Nothing has been saved yet.",
    }


async def confirm_pending(ctx: ToolContext, a: ConfirmPendingArgs) -> dict:
    if not ctx.speaker_is_owner:
        # The gate is an authorization check, not a formality.
        return {"error": "not_the_owner",
                "detail": "Only the shop owner can confirm a khata entry."}
    try:
        pid = UUID(a.pending_id)
    except ValueError:
        return {"error": "bad_pending_id"}

    pending = await ctx.session.scalar(
        select(PendingAction).where(
            PendingAction.id == pid,
            PendingAction.store_id == ctx.store.id,   # tenant scope
        )
    )
    if not pending:
        return {"error": "not_found"}
    if pending.status != "awaiting":
        return {"error": "already_resolved", "status": pending.status}
    if pending.expires_at < datetime.now(UTC):
        pending.status = "expired"
        return {"error": "expired",
                "detail": "That confirmation timed out. Propose the entry again."}

    if not a.confirm:
        pending.status = "cancelled"
        return {"status": "cancelled", "detail": "Nothing was saved."}

    args = pending.args
    c = await _customer_by_mobile(ctx, args["customer_mobile"])
    if not c:
        return {"error": "no_such_customer"}

    entry, new_balance = await ledger.add_entry(
        ctx.session, ctx.settings,
        store=ctx.store, customer=c,
        kind=args["kind"],
        amount=Decimal(args["amount"]),
        note=args.get("note"),
        created_via="text",
        # The pending action's own id is the idempotency key: confirming twice
        # cannot produce two ledger rows even if the model repeats the call.
        request_id=f"gate-{pending.id}",
    )
    pending.status = "confirmed"
    pending.result_id = entry.id

    log.info("gate: entry committed", extra={
        "pending_id": str(pending.id), "entry_id": str(entry.id),
        "balance": str(new_balance),
    })
    return {
        "status": "saved",
        "customer": c.name,
        "amount": str(entry.amount),
        "new_balance": str(new_balance),
        "notified": bool(c.email and c.notify_email),
    }


# ---- registry ------------------------------------------------------------

_REGISTRY: dict[str, tuple[type[BaseModel], object]] = {
    "find_customer": (FindCustomerArgs, find_customer),
    "create_customer": (CreateCustomerArgs, create_customer),
    "get_khata": (GetKhataArgs, get_khata),
    "add_khata_entry": (AddKhataEntryArgs, add_khata_entry),
    "confirm_pending": (ConfirmPendingArgs, confirm_pending),
}


def _simplify(prop: dict) -> dict:
    """Flatten Pydantic's Decimal rendering.

    Pydantic emits `Decimal` as anyOf[number, string] where the string variant
    carries a regex with a negative lookahead. Several providers' schema
    validators reject lookahead patterns outright, and the anyOf tells the model
    nothing useful. Money is a JSON number on the wire; Pydantic still parses it
    into an exact Decimal on the way in, so nothing about precision changes.
    """
    variants = prop.get("anyOf")
    if variants and {v.get("type") for v in variants} == {"number", "string"}:
        rest = {k: v for k, v in prop.items() if k != "anyOf"}
        return {**rest, "type": "number"}
    return prop


def _tool_def(name: str, args: type[BaseModel]) -> dict:
    schema = args.model_json_schema()
    schema.pop("title", None)
    props = schema.get("properties", {})
    for key, prop in list(props.items()):
        prop.pop("title", None)
        props[key] = _simplify(prop)
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": " ".join((args.__doc__ or "").split()),
            "parameters": schema,
        },
    }


TOOL_DEFS: list[dict] = [
    _tool_def(name, model) for name, (model, _) in _REGISTRY.items()
]


async def dispatch(ctx: ToolContext, name: str, raw_args: str) -> str:
    """Run one tool call and return a JSON string for the tool message.

    Every failure path returns a result the model can act on rather than
    raising: a tool error is a turn the agent can recover from, an exception is
    a 500 the owner sees.
    """
    entry = _REGISTRY.get(name)
    if entry is None:
        return json.dumps({"error": "unknown_tool", "tool": name})
    model, handler = entry

    try:
        parsed = json.loads(raw_args or "{}")
    except json.JSONDecodeError:
        return json.dumps({"error": "bad_json",
                           "detail": "Arguments were not valid JSON. Try again."})
    try:
        validated = model.model_validate(parsed)
    except (ValidationError, InvalidOperation) as e:
        return json.dumps({"error": "bad_arguments", "detail": str(e)[:600]})

    try:
        result = await handler(ctx, validated)
    except ValueError as e:
        # Domain refusals (bad amount, wrong store) are recoverable.
        return json.dumps({"error": "rejected", "detail": str(e)[:300]})

    log.info("tool call", extra={"tool": name})
    return json.dumps(result, default=str, ensure_ascii=False)


def new_request_id() -> str:
    return uuid4().hex
