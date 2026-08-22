"""The store agent: a bounded tool-calling loop over an OpenAI-compatible API.

No LangChain, no LangGraph. The two things a framework would provide for this
shape are durable conversation state and human-in-the-loop pausing, and both
already exist here in forms we cannot give up: `messages` is the audit trail
money requires, and the confirmation gate is an authorization check on a
persisted row -- resolved by a separate authenticated request, possibly minutes
later and by a different worker -- not a paused execution. See the plan's §2 for
the two triggers that should overturn that decision.

Provider is three env vars. Currently xAI Grok via its OpenAI-compatible
endpoint; `LLM_BASE_URL` is the only thing that changes to move to Sarvam-M.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from openai import APIError, AsyncOpenAI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Conversation, Message, Store
from app.tools import TOOL_DEFS, ToolContext, dispatch

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are the assistant for {store_name}, a small shop. You are speaking with \
{owner_name}, the owner. Everything you say is read aloud, so reply in one or \
two short sentences — never a list, never a paragraph.

Reply in the owner's language, which is {owner_language}. The owner may speak \
to you in a mix of languages; answer in {owner_language} regardless.

Your job is the khata: the shop's credit ledger. You can look up customers, \
read what they owe, register new customers, and record credit given or \
payments received.

Rules you must not break:

1. Money is never saved on your first call. add_khata_entry only proposes an \
entry and returns a summary. Read that summary back to the owner, ask if it is \
correct, and only call confirm_pending after they answer.
2. Never invent a mobile number, a name, or an amount. Use find_customer to \
get a customer's exact mobile number before recording anything against them. \
If you do not know an amount, ask.
3. If find_customer returns more than one person, ask the owner which one they \
mean. Do not guess.
4. Amounts are in rupees. State them plainly, e.g. 340.50.
5. If a tool returns an error, tell the owner what is needed in plain language. \
Do not retry the same call unchanged.

Today is {today} in the shop's timezone."""


@dataclass
class AgentReply:
    text: str
    tool_calls_made: list[str]
    hops: int
    conversation_id: UUID
    truncated: bool = False   # True when the hop ceiling stopped the loop


def _client(settings: Settings) -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key or "unset",
        timeout=45.0,
        max_retries=2,
    )


async def get_or_create_conversation(
    s: AsyncSession, store: Store, conversation_id: UUID | None
) -> Conversation:
    if conversation_id:
        conv = await s.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.store_id == store.id,   # tenant scope
            )
        )
        if conv:
            return conv
    conv = Conversation(store_id=store.id, mode="agent")
    s.add(conv)
    await s.flush()
    return conv


async def load_history(s: AsyncSession, conversation_id: UUID) -> list[dict]:
    """Replay the wire-format messages for this conversation.

    `content` holds the raw chat-completions message, so this is byte-exact --
    which is what lets the confirmation arrive in a separate HTTP request.
    """
    rows = (await s.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id,
               Message.api_role.is_not(None))
        .order_by(Message.seq)
    )).all()
    return [r.content for r in rows]


async def _next_seq(s: AsyncSession, conversation_id: UUID) -> int:
    top = await s.scalar(
        select(func.coalesce(func.max(Message.seq), 0))
        .where(Message.conversation_id == conversation_id)
    )
    return int(top) + 1


async def persist(
    s: AsyncSession,
    conversation_id: UUID,
    *,
    api_role: str,
    content: dict,
    role: str,
    text: str | None = None,
) -> None:
    s.add(Message(
        conversation_id=conversation_id,
        seq=await _next_seq(s, conversation_id),
        role=role,
        api_role=api_role,
        content=content,
        text_original=text,
    ))
    await s.flush()


async def run_turn(
    s: AsyncSession,
    settings: Settings,
    *,
    store: Store,
    conversation: Conversation,
    user_text: str,
    speaker_is_owner: bool = True,
    client: Any | None = None,
) -> AgentReply:
    """One owner turn: think, call tools, answer.

    `client` is injectable so the loop can be driven by a scripted stub in
    tests -- the orchestration is verifiable with no provider and no API key.
    """
    llm = client or _client(settings)
    ctx = ToolContext(
        session=s, store=store, settings=settings,
        conversation_id=conversation.id, speaker_is_owner=speaker_is_owner,
    )

    system = {
        "role": "system",
        "content": SYSTEM_PROMPT.format(
            store_name=store.name,
            owner_name=store.owner_name,
            owner_language=store.owner_language,
            today=_today_in_store(store),
        ),
    }
    history = await load_history(s, conversation.id)
    user_msg = {"role": "user", "content": user_text}
    await persist(s, conversation.id, api_role="user", content=user_msg,
                  role="owner", text=user_text)

    messages: list[dict] = [system, *history, user_msg]
    called: list[str] = []
    reply_text = ""
    hops = 0
    truncated = True   # set False the moment the model finishes cleanly

    for hop in range(1, settings.max_tool_hops + 1):
        # Tracked outside the loop on purpose: the caller reports how many
        # round-trips the turn cost, and the ceiling guards a free-tier quota.
        hops = hop
        try:
            resp = await llm.chat.completions.create(
                model=settings.llm_model,
                messages=messages,
                tools=TOOL_DEFS,
                tool_choice="auto",
                temperature=0,      # this path writes to a ledger
                max_tokens=1024,    # a long spoken reply is a bug, not a feature
            )
        except APIError as e:
            # A provider failure must not look like a refusal to the owner, and
            # must not leave a half-written turn behind.
            log.warning("llm call failed", extra={"error": type(e).__name__})
            raise

        choice = resp.choices[0]
        msg = choice.message
        wire = msg.model_dump(exclude_none=True)
        messages.append(wire)
        await persist(s, conversation.id, api_role="assistant", content=wire,
                      role="agent", text=msg.content)

        if not msg.tool_calls:
            reply_text = (msg.content or "").strip()
            truncated = False
            break

        for tc in msg.tool_calls:
            name = tc.function.name
            called.append(name)
            result = await dispatch(ctx, name, tc.function.arguments)
            tool_msg = {"role": "tool", "tool_call_id": tc.id, "content": result}
            messages.append(tool_msg)
            await persist(s, conversation.id, api_role="tool",
                          content=tool_msg, role="tool")
    else:
        # Ran out of hops with the model still calling tools. On a free tier
        # this ceiling protects the day's quota, not just the bill.
        log.warning("hop ceiling reached", extra={"hops": hops, "calls": called})
        reply_text = reply_text or (
            "I could not finish that. Please say it again, more simply."
        )

    log.info("agent turn done", extra={
        "hops": hops, "tools": ",".join(called) or "none",
        "truncated": truncated,
    })
    return AgentReply(
        text=reply_text,
        tool_calls_made=called,
        hops=hops,
        conversation_id=conversation.id,
        truncated=truncated,
    )


def _today_in_store(store: Store) -> str:
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo
    return datetime.now(UTC).astimezone(
        ZoneInfo(store.timezone)
    ).strftime("%d %B %Y")


def probe_tools_payload() -> str:
    """The tool block we send, for eyeballing what a new provider receives.
    Useful on the first call against a provider that has not been tried."""
    return json.dumps(TOOL_DEFS, indent=2)
