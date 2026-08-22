"""The agent's HTTP surface.

Text rather than audio on purpose: the whole agent is drivable with curl before
any of the voice pipeline exists, which is where the tool-selection behaviour
gets shaken out cheaply.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from openai import APIError

from app import agent
from app.db import SessionDep, SettingsDep, StoreDep
from app.schemas import AgentTextRequest, AgentTextResponse

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/agent", tags=["agent"])


@router.post("/text", response_model=AgentTextResponse)
async def agent_text(
    body: AgentTextRequest,
    store: StoreDep,
    session: SessionDep,
    settings: SettingsDep,
) -> AgentTextResponse:
    """Send the owner's words to the agent and get back what to say.

    The bearer token authenticates the store owner, so a request here is
    owner-spoken by definition -- `speaker_is_owner` is True. On the voice path
    that flag comes from the voiceprint stage instead, and the confirmation gate
    checks it before committing anything.
    """
    if not settings.llm_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No LLM configured. Set LLM_BASE_URL, LLM_API_KEY and "
                   "LLM_MODEL in .env.",
        )

    conversation = await agent.get_or_create_conversation(
        session, store, body.conversation_id
    )
    try:
        reply = await agent.run_turn(
            session, settings,
            store=store,
            conversation=conversation,
            user_text=body.text,
            speaker_is_owner=True,
        )
    except APIError as e:
        # Upstream provider failure. 502, not 500: nothing is wrong with us, and
        # the distinction matters when a free-tier quota runs out mid-demo.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"The language model is unavailable ({type(e).__name__}).",
        ) from e

    return AgentTextResponse(
        reply=reply.text,
        conversation_id=reply.conversation_id,
        language=store.owner_language,
        tools_used=reply.tool_calls_made,
        hops=reply.hops,
        truncated=reply.truncated,
    )
