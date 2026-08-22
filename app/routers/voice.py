"""Sarvam STT / TTS for the shop UI. No speaker-ID yet — the bearer is the owner."""

from __future__ import annotations

import base64
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.db import SessionDep, SettingsDep, StoreDep
from app.models import VoiceUtterance
from app.services import sarvam
from app.services.sarvam import SarvamError

router = APIRouter(prefix="/v1/voice", tags=["voice"])


class TranscriptOut(BaseModel):
    transcript: str
    language: str | None = None
    utterance_id: str


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    language: str = Field(min_length=2, max_length=16)


class SpeakOut(BaseModel):
    audio_base64: str
    mime: str = "audio/wav"


@router.post("/transcribe", response_model=TranscriptOut)
async def transcribe(
    store: StoreDep,
    session: SessionDep,
    settings: SettingsDep,
    file: UploadFile = File(...),
) -> TranscriptOut:
    audio = await file.read()
    if not audio:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Empty audio.")
    settings.audio_dir.mkdir(parents=True, exist_ok=True)
    name = f"{uuid4().hex}{_suffix(file.filename)}"
    path = settings.audio_dir / name
    path.write_bytes(audio)

    try:
        result = await sarvam.transcribe(
            settings, audio, file.filename or name,
            file.content_type or "application/octet-stream",
        )
    except SarvamError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e

    row = VoiceUtterance(
        store_id=store.id,
        speaker_role="owner",
        audio_uri=str(path),
        transcript=result.text,
        detected_language=result.language,
        stt_provider="sarvam",
    )
    session.add(row)
    await session.flush()
    return TranscriptOut(
        transcript=result.text,
        language=result.language,
        utterance_id=str(row.id),
    )


@router.post("/speak", response_model=SpeakOut)
async def speak(body: SpeakIn, _store: StoreDep, settings: SettingsDep) -> SpeakOut:
    try:
        raw = await sarvam.synthesize(settings, body.text, body.language)
    except SarvamError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e
    return SpeakOut(audio_base64=base64.b64encode(raw).decode("ascii"))


def _suffix(filename: str | None) -> str:
    if not filename or "." not in filename:
        return ".webm"
    return "." + filename.rsplit(".", 1)[-1][:8]
