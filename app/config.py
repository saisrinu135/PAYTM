"""Application settings. Every value comes from the environment or .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- app ------------------------------------------------------------
    env: Literal["dev", "prod"] = "dev"
    log_level: str = "DEBUG"
    log_format: Literal["console", "json"] = "console"
    # NoDecode: without it pydantic-settings JSON-decodes list fields at the
    # source, before the validator below can split the comma-separated form
    # that a .env file / compose environment block actually carries.
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # ---- database -------------------------------------------------------
    database_url: str = "postgresql+asyncpg://smb:smb@localhost:5432/smb_agent"
    db_echo: bool = False

    # ---- LLM (agent tool loop only -- the bridge never calls an LLM) ----
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4.1"
    max_tool_hops: int = 6

    # ---- Sarvam: STT / TTS / translate ----------------------------------
    sarvam_api_key: str = ""
    sarvam_base_url: str = "https://api.sarvam.ai"

    # ---- voice ----------------------------------------------------------
    audio_dir: Path = Path("./media")
    models_dir: Path = Path("./models")
    ffmpeg_bin: str = "ffmpeg"
    wake_word: str = "sathi"
    vad_silence_ms: int = 600
    speaker_threshold_default: float = 0.70

    # ---- email ----------------------------------------------------------
    # Defaults target the local Mailpit catcher: port 1025, no auth, no TLS.
    # A real provider needs smtp_starttls=True plus user/password.
    smtp_host: str = ""
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = False
    smtp_from: str = "noreply@example.com"
    smtp_timeout: int = 10
    notify_sweep_seconds: int = 900

    @property
    def email_enabled(self) -> bool:
        """No SMTP host means notifications are skipped, not failed. A shop
        without mail configured should still be able to record khata."""
        return bool(self.smtp_host)

    @field_validator("smtp_starttls")
    @classmethod
    def _require_tls_in_prod(cls, v: bool, info) -> bool:
        """Refuse to ship credentials in the clear. Mailpit needs plaintext,
        but that is a dev-only concession and must not survive to prod."""
        if not v and info.data.get("env") == "prod" and info.data.get("smtp_user"):
            raise ValueError(
                "SMTP_STARTTLS must be true in prod when SMTP_USER is set -- "
                "otherwise the password goes over the wire in plaintext."
            )
        return v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        """Accept CORS_ORIGINS as a comma-separated string, which is how it
        arrives from a .env file or a compose environment block."""
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"


@lru_cache
def get_settings() -> Settings:
    """Cached so .env is parsed once per process. Tests override by clearing
    the cache: get_settings.cache_clear()."""
    return Settings()
