"""Owner ↔ customer interpreter. Sarvam only — no LLM, no tools."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.db import SessionDep, SettingsDep, StoreDep
from app.models import Conversation, Message
from app.services import sarvam
from app.services.sarvam import SarvamError

router = APIRouter(prefix="/v1/bridge", tags=["bridge"])

Speaker = Literal["owner", "customer"]


class BridgeTextIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    speaker: Speaker
    customer_language: str = Field(min_length=2, max_length=16)
    conversation_id: UUID | None = None


class BridgeTextOut(BaseModel):
    conversation_id: UUID
    speaker: Speaker
    original: str
    original_language: str
    translated: str
    translated_language: str


def _langs(store_lang: str, customer_lang: str, speaker: Speaker) -> tuple[str, str]:
    if speaker == "owner":
        return store_lang, customer_lang
    return customer_lang, store_lang


async def _conversation(
    session, store_id, conversation_id: UUID | None,
) -> Conversation:
    if conversation_id:
        conv = await session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.store_id == store_id,
                Conversation.mode == "bridge",
            )
        )
        if conv:
            return conv
    conv = Conversation(store_id=store_id, mode="bridge")
    session.add(conv)
    await session.flush()
    return conv


@router.post("/text", response_model=BridgeTextOut)
async def bridge_text(
    body: BridgeTextIn,
    store: StoreDep,
    session: SessionDep,
    settings: SettingsDep,
) -> BridgeTextOut:
    source, target = _langs(store.owner_language, body.customer_language, body.speaker)
    try:
        translated = await sarvam.translate(
            settings, body.text, source=source, target=target,
        )
    except SarvamError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e

    conv = await _conversation(session, store.id, body.conversation_id)
    top = await session.scalar(
        select(func.coalesce(func.max(Message.seq), 0))
        .where(Message.conversation_id == conv.id)
    )
    session.add(Message(
        conversation_id=conv.id,
        seq=int(top) + 1,
        role=body.speaker,
        api_role=None,
        content={"original": body.text, "translated": translated},
        text_original=body.text,
        lang_original=source,
        text_translated=translated,
        lang_translated=target,
    ))
    await session.flush()
    return BridgeTextOut(
        conversation_id=conv.id,
        speaker=body.speaker,
        original=body.text,
        original_language=source,
        translated=translated,
        translated_language=target,
    )
