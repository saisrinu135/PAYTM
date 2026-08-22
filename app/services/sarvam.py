"""Sarvam REST: translate, STT, TTS. The bridge never goes through an LLM."""

from __future__ import annotations

import asyncio
import base64
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx2

from app.config import Settings

log = logging.getLogger(__name__)

_SARVAM_AUDIO = {
    "audio/mpeg", "audio/mp3", "audio/mpeg3", "audio/x-mpeg-3", "audio/x-mp3",
    "audio/wav", "audio/x-wav", "audio/wave",
}


class SarvamError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


@dataclass
class Transcript:
    text: str
    language: str | None


def _require(settings: Settings) -> None:
    if not settings.sarvam_api_key:
        raise SarvamError(
            "No Sarvam key. Set SARVAM_API_KEY in .env.",
            status=503,
        )


def _fail(kind: str, r: httpx2.Response) -> None:
    snippet = (r.text or "")[:400]
    log.warning("sarvam %s failed", kind, extra={"status": r.status_code, "body": snippet})
    raise SarvamError(f"Sarvam {kind} failed ({r.status_code}): {snippet[:180]}")


def _headers(settings: Settings) -> dict[str, str]:
    return {"api-subscription-key": settings.sarvam_api_key}


def _mime(content_type: str) -> str:
    return (content_type or "").split(";")[0].strip().lower()


async def _to_wav(settings: Settings, audio: bytes, filename: str) -> bytes:
    """Browser recordings are webm/opus. Sarvam only takes wav/mp3."""
    suffix = Path(filename).suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as src:
        src.write(audio)
        src_path = src.name
    dst_path = src_path + ".wav"
    try:
        proc = await asyncio.create_subprocess_exec(
            settings.ffmpeg_bin, "-y", "-i", src_path,
            "-ar", "16000", "-ac", "1", "-f", "wav", dst_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            raise SarvamError(
                "ffmpeg could not decode the recording. "
                f"{err.decode('utf-8', 'replace')[-200:]}",
                status=422,
            )
        return Path(dst_path).read_bytes()
    finally:
        Path(src_path).unlink(missing_ok=True)
        Path(dst_path).unlink(missing_ok=True)


async def translate(
    settings: Settings,
    text: str,
    *,
    source: str,
    target: str,
) -> str:
    if source.split("-")[0].lower() == target.split("-")[0].lower():
        return text
    _require(settings)
    url = f"{settings.sarvam_base_url.rstrip('/')}/translate"
    payload = {
        "input": text,
        "source_language_code": source,
        "target_language_code": target,
        "model": settings.sarvam_translate_model,
        "mode": "formal",
        "enable_preprocessing": True,
    }
    async with httpx2.AsyncClient(timeout=45.0) as client:
        r = await client.post(url, headers=_headers(settings), json=payload)
    if r.status_code >= 400:
        _fail("translate", r)
    data = r.json()
    return (data.get("translated_text") or data.get("output") or "").strip() or text


async def transcribe(
    settings: Settings,
    audio: bytes,
    filename: str,
    content_type: str,
    language_code: str = "unknown",
) -> Transcript:
    _require(settings)
    if _mime(content_type) not in _SARVAM_AUDIO:
        audio = await _to_wav(settings, audio, filename)
        filename, content_type = "clip.wav", "audio/wav"
    url = f"{settings.sarvam_base_url.rstrip('/')}/speech-to-text"
    files = {"file": (filename, audio, content_type or "application/octet-stream")}
    data = {
        "model": settings.sarvam_stt_model,
        "mode": "transcribe",
        "language_code": language_code,
    }
    async with httpx2.AsyncClient(timeout=60.0) as client:
        r = await client.post(
            url, headers=_headers(settings), files=files, data=data,
        )
    if r.status_code >= 400:
        _fail("stt", r)
    body = r.json()
    return Transcript(
        text=(body.get("transcript") or body.get("text") or "").strip(),
        language=body.get("language_code"),
    )


async def synthesize(
    settings: Settings,
    text: str,
    language: str,
) -> bytes:
    _require(settings)
    url = f"{settings.sarvam_base_url.rstrip('/')}/text-to-speech"
    payload = {
        "inputs": [text],
        "target_language_code": language,
        "speaker": "anushka",
        "model": "bulbul:v2",
    }
    async with httpx2.AsyncClient(timeout=45.0) as client:
        r = await client.post(url, headers=_headers(settings), json=payload)
    if r.status_code >= 400:
        _fail("tts", r)
    audios = r.json().get("audios") or []
    if not audios:
        raise SarvamError("Sarvam TTS returned no audio.")
    return base64.b64decode(audios[0])
