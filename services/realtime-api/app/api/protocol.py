from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class EventEnvelope(BaseModel):
    type: str
    sessionId: str | None = None
    turnId: str | None = None
    seq: int = Field(default=0, ge=0)
    timestamp: datetime
    payload: dict[str, Any]


class SessionStartPayload(BaseModel):
    sampleRate: int = 16000
    format: Literal["pcm_s16le"] = "pcm_s16le"
    language: Literal["en"] = "en"

