"""Agent orchestration, verified with no provider and no API key.

A scripted stub stands in for the LLM, which is what makes the risky parts
testable before anyone spends a token: dispatch, the confirmation gate, the hop
ceiling, history across a request boundary, and tenant isolation.

Run:  pytest tests/test_agent.py -v
Needs the compose database up and `alembic upgrade head && python -m seeds.seed`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import delete, func, select

from app import agent
from app.models import Customer, LedgerEntry, Notification, PendingAction, Store
from app.services import ledger

# ---- the stub -------------------------------------------------------------
# Shapes just enough of the openai response object for the loop to walk it.

@dataclass
class _Fn:
    name: str
    arguments: str


@dataclass
class _ToolCall:
    id: str
    function: _Fn
    type: str = "function"


@dataclass
class _Msg:
    role: str = "assistant"
    content: str | None = None
    tool_calls: list[_ToolCall] | None = None

    def model_dump(self, **_: Any) -> dict:
        out: dict[str, Any] = {"role": self.role}
        if self.content is not None:
            out["content"] = self.content
        if self.tool_calls:
            out["tool_calls"] = [
                {"id": t.id, "type": "function",
                 "function": {"name": t.function.name,
                              "arguments": t.function.arguments}}
                for t in self.tool_calls
            ]
        return out


@dataclass
class _Choice:
    message: _Msg
    finish_reason: str = "stop"


@dataclass
class _Resp:
    choices: list[_Choice]


class StubLLM:
    """Replays a scripted list of turns. Records what it was sent, so a test can
    assert on the tool block the provider would have received."""

    def __init__(self, script: list[_Msg]):
        self.script = list(script)
        self.sent: list[dict] = []
        self.chat = self  # so `llm.chat.completions.create` resolves
        self.completions = self

    async def create(self, **kwargs) -> _Resp:
        # Snapshot the message list: run_turn keeps appending to the same list
        # object, so storing the kwargs by reference would show later mutations.
        self.sent.append({**kwargs, "messages": list(kwargs["messages"])})
        msg = self.script.pop(0) if self.script else _Msg(content="done")
        return _Resp([_Choice(msg, "tool_calls" if msg.tool_calls else "stop")])


def call(name: str, **args) -> _Msg:
    return _Msg(tool_calls=[
        _ToolCall(id=f"c_{name}", function=_Fn(name, json.dumps(args)))
    ])


def say(text: str) -> _Msg:
    return _Msg(content=text)


# ---- fixtures -------------------------------------------------------------
# `settings` and `sm` come from conftest.py, session-scoped alongside the engine.

@pytest.fixture
async def ctx(sm):
    """The seeded store plus its customers, as plain ids."""
    async with sm() as s:
        store_id = await s.scalar(
            select(Store.id).where(Store.owner_mobile == "+919876543210")
        )
        assert store_id, "run `python -m seeds.seed` first"
        ramesh = await s.scalar(
            select(Customer.mobile).where(Customer.mobile == "+919812345678")
        )
        # Clear anything a previous run left behind.
        await s.execute(delete(PendingAction).where(
            PendingAction.store_id == store_id))
        await s.execute(delete(Notification).where(
            Notification.store_id == store_id))
        await s.commit()
    return {"store_id": store_id, "ramesh": ramesh}


async def _run(sm, settings, store_id, script, text, conv_id=None,
               speaker_is_owner=True):
    stub = StubLLM(script)
    async with sm() as s:
        store = await s.get(Store, store_id)
        conv = await agent.get_or_create_conversation(s, store, conv_id)
        reply = await agent.run_turn(
            s, settings, store=store, conversation=conv, user_text=text,
            speaker_is_owner=speaker_is_owner, client=stub,
        )
        await s.commit()
    return reply, stub


def _last_tool(stub) -> dict:
    """The most recent tool result the model was shown.

    Not the first: by turn two the message list carries the whole conversation,
    including earlier turns' tool results.
    """
    return [m for m in stub.sent[-1]["messages"] if m.get("role") == "tool"][-1]


async def _ledger_count(sm, store_id) -> int:
    async with sm() as s:
        return await s.scalar(
            select(func.count()).select_from(LedgerEntry)
            .where(LedgerEntry.store_id == store_id)
        )


async def _customer_balance(sm, mobile: str) -> Decimal:
    async with sm() as s:
        cid = await s.scalar(select(Customer.id).where(Customer.mobile == mobile))
        return await ledger.balance(s, cid)


# ---- 1. dispatch ---------------------------------------------------------

async def test_dispatch_reaches_the_tool(sm, settings, ctx):
    owed = await _customer_balance(sm, ctx["ramesh"])
    reply, stub = await _run(
        sm, settings, ctx["store_id"],
        [call("get_khata", customer_mobile=ctx["ramesh"]),
         say(f"Ramesh owes {owed} rupees.")],
        "ramesh ka kitna baaki hai?",
    )
    assert reply.tool_calls_made == ["get_khata"]
    assert str(owed) in reply.text
    # the tool result actually carried the balance back to the model
    tool_msg = _last_tool(stub)
    assert json.loads(tool_msg["content"])["balance"] == str(owed)


async def test_tools_sent_without_strict(sm, settings, ctx):
    """Grok, Sarvam-M and friends reject `strict: true`."""
    _, stub = await _run(sm, settings, ctx["store_id"], [say("hello")], "hi")
    blob = json.dumps(stub.sent[0]["tools"])
    assert "strict" not in blob
    assert "$ref" not in blob and "$defs" not in blob
    assert stub.sent[0]["temperature"] == 0


# ---- 2. the gate ---------------------------------------------------------

async def test_proposing_writes_no_ledger_row(sm, settings, ctx):
    before = await _ledger_count(sm, ctx["store_id"])
    reply, _ = await _run(
        sm, settings, ctx["store_id"],
        [call("add_khata_entry", customer_mobile=ctx["ramesh"],
              kind="credit_given", amount=340.50, note="oil and atta"),
         say("340.50 credit for Ramesh Kumar, for oil and atta. Correct?")],
        "ramesh ko 340.50 udhaar likho",
    )
    assert reply.tool_calls_made == ["add_khata_entry"]
    assert await _ledger_count(sm, ctx["store_id"]) == before, \
        "the gate leaked: a ledger row was written before confirmation"

    async with sm() as s:
        pending = await s.scalar(select(PendingAction).where(
            PendingAction.store_id == ctx["store_id"]))
        assert pending.status == "awaiting"
        assert pending.args["amount"] == "340.50"


async def test_confirm_commits_and_queues_the_email(sm, settings, ctx):
    before = await _ledger_count(sm, ctx["store_id"])
    before_bal = await _customer_balance(sm, ctx["ramesh"])
    expected_bal = str(before_bal + Decimal("340.50"))
    r1, _ = await _run(
        sm, settings, ctx["store_id"],
        [call("add_khata_entry", customer_mobile=ctx["ramesh"],
              kind="credit_given", amount=340.50),
         say("340.50 for Ramesh. Correct?")],
        "ramesh ko 340.50 udhaar",
    )
    async with sm() as s:
        pid = str((await s.scalar(select(PendingAction).where(
            PendingAction.store_id == ctx["store_id"]))).id)

    # Separate turn, same conversation -- the confirmation is its own request.
    r2, _ = await _run(
        sm, settings, ctx["store_id"],
        [call("confirm_pending", pending_id=pid, confirm=True),
         say(f"Saved. Ramesh now owes {expected_bal}.")],
        "haan", conv_id=r1.conversation_id,
    )
    assert r2.tool_calls_made == ["confirm_pending"]
    assert await _ledger_count(sm, ctx["store_id"]) == before + 1

    async with sm() as s:
        assert (await s.scalar(select(PendingAction.status).where(
            PendingAction.id == pid))) == "confirmed"
        n = await s.scalar(select(Notification).where(
            Notification.store_id == ctx["store_id"]))
        assert n is not None and n.status == "queued"
        assert n.payload["balance"] == expected_bal


async def test_declining_saves_nothing(sm, settings, ctx):
    before = await _ledger_count(sm, ctx["store_id"])
    r1, _ = await _run(
        sm, settings, ctx["store_id"],
        [call("add_khata_entry", customer_mobile=ctx["ramesh"],
              kind="credit_given", amount=9999.00),
         say("9999 for Ramesh. Correct?")],
        "ramesh ko 9999 likho",
    )
    async with sm() as s:
        pid = str((await s.scalar(select(PendingAction).where(
            PendingAction.store_id == ctx["store_id"]))).id)
    await _run(
        sm, settings, ctx["store_id"],
        [call("confirm_pending", pending_id=pid, confirm=False),
         say("Cancelled.")],
        "nahi", conv_id=r1.conversation_id,
    )
    assert await _ledger_count(sm, ctx["store_id"]) == before
    async with sm() as s:
        assert (await s.scalar(select(PendingAction.status).where(
            PendingAction.id == pid))) == "cancelled"


async def test_only_the_owner_may_confirm(sm, settings, ctx):
    """The gate is an authorization check, not a formality."""
    before = await _ledger_count(sm, ctx["store_id"])
    r1, _ = await _run(
        sm, settings, ctx["store_id"],
        [call("add_khata_entry", customer_mobile=ctx["ramesh"],
              kind="credit_given", amount=500.00), say("500. Correct?")],
        "500 likho",
    )
    async with sm() as s:
        pid = str((await s.scalar(select(PendingAction).where(
            PendingAction.store_id == ctx["store_id"]))).id)

    _, stub = await _run(
        sm, settings, ctx["store_id"],
        [call("confirm_pending", pending_id=pid, confirm=True),
         say("Only the owner can confirm that.")],
        "yes", conv_id=r1.conversation_id, speaker_is_owner=False,
    )
    assert await _ledger_count(sm, ctx["store_id"]) == before
    tool_msg = _last_tool(stub)
    assert json.loads(tool_msg["content"])["error"] == "not_the_owner"


# ---- 3. the hop ceiling --------------------------------------------------

async def test_runaway_loop_terminates(sm, settings, ctx):
    """A confused model must not burn the day's free-tier quota."""
    forever = [call("get_khata", customer_mobile=ctx["ramesh"])
               for _ in range(50)]
    reply, stub = await _run(sm, settings, ctx["store_id"], forever, "loop")
    assert reply.hops == settings.max_tool_hops
    assert reply.truncated is True
    assert len(stub.sent) == settings.max_tool_hops
    assert reply.text, "a truncated turn must still say something to the owner"


# ---- 4. history across the request boundary ------------------------------

async def test_history_replays_into_the_next_turn(sm, settings, ctx):
    r1, _ = await _run(sm, settings, ctx["store_id"],
                       [say("Which Ramesh do you mean?")], "ramesh")
    _, stub = await _run(sm, settings, ctx["store_id"],
                         [say("Understood.")], "the one with the shop",
                         conv_id=r1.conversation_id)
    roles = [m["role"] for m in stub.sent[0]["messages"]]
    assert roles[0] == "system"
    # turn 1's user + assistant, then turn 2's user
    assert roles[1:] == ["user", "assistant", "user"]
    contents = [m.get("content") for m in stub.sent[0]["messages"]]
    assert "ramesh" in contents
    assert "Which Ramesh do you mean?" in contents


# ---- 5. tenant isolation -------------------------------------------------

async def test_tool_cannot_reach_another_store(sm, settings, ctx):
    """A second store's customer must be invisible, even named exactly."""
    async with sm() as s:
        other = Store(name="Other Shop", owner_name="Someone",
                      owner_mobile="+919000000111", api_token_hash="other")
        s.add(other)
        await s.flush()
        s.add(Customer(store_id=other.id, mobile="+919111222333",
                       name="Hidden Person"))
        await s.commit()
        other_id = other.id

    _, stub = await _run(
        sm, settings, ctx["store_id"],
        [call("get_khata", customer_mobile="+919111222333"),
         say("I could not find that customer.")],
        "hidden person ka khata dikhao",
    )
    tool_msg = _last_tool(stub)
    assert json.loads(tool_msg["content"])["error"] == "no_such_customer"

    async with sm() as s:
        await s.execute(delete(Store).where(Store.id == other_id))
        await s.commit()


# ---- 6. malformed tool arguments -----------------------------------------

async def test_bad_arguments_are_recoverable(sm, settings, ctx):
    """A validation failure is a turn the model can retry, not a 500."""
    bad = _Msg(tool_calls=[_ToolCall(
        id="c1", function=_Fn("add_khata_entry", '{"customer_mobile":"'
                              + ctx["ramesh"] + '","kind":"credit_given",'
                              '"amount":-5}'))])
    _, stub = await _run(sm, settings, ctx["store_id"],
                         [bad, say("Amount must be positive.")], "minus five")
    tool_msg = _last_tool(stub)
    assert json.loads(tool_msg["content"])["error"] == "bad_arguments"


async def test_invalid_json_is_recoverable(sm, settings, ctx):
    broken = _Msg(tool_calls=[_ToolCall(
        id="c1", function=_Fn("get_khata", "{not json"))])
    _, stub = await _run(sm, settings, ctx["store_id"],
                         [broken, say("Let me try again.")], "x")
    tool_msg = _last_tool(stub)
    assert json.loads(tool_msg["content"])["error"] == "bad_json"


async def test_unknown_tool_is_recoverable(sm, settings, ctx):
    ghost = _Msg(tool_calls=[_ToolCall(
        id="c1", function=_Fn("delete_everything", "{}"))])
    _, stub = await _run(sm, settings, ctx["store_id"],
                         [ghost, say("I cannot do that.")], "x")
    tool_msg = _last_tool(stub)
    assert json.loads(tool_msg["content"])["error"] == "unknown_tool"
