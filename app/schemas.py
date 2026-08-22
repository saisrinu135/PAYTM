"""API request and response models. The HTTP surface, not the tables."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class AgentTextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000,
                      description="What the owner said or typed")
    conversation_id: UUID | None = Field(
        default=None,
        description="Omit to start a new conversation. Pass the id returned by "
                    "the previous call to continue one -- required for the "
                    "confirmation step, which is a separate request.",
    )


class AgentTextResponse(BaseModel):
    reply: str = Field(description="What to say back to the owner")
    conversation_id: UUID = Field(description="Pass this to the next call")
    language: str = Field(description="Language the reply is in")
    tools_used: list[str] = Field(default_factory=list)
    hops: int = Field(description="LLM round-trips this turn consumed")
    truncated: bool = Field(
        default=False,
        description="True if the tool-hop ceiling stopped the turn early",
    )
