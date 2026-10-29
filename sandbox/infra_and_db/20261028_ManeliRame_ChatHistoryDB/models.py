"""
models.py

Pydantic models: the first validation layer of the chat-history PoC.
Every record must pass these models before it is allowed near the
database. The CHECK constraints in schema.sql are the second layer.
"""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

# Only these roles are legal in a chat transcript.
Role = Literal["system", "user", "assistant", "tool"]


class ConversationIn(BaseModel):
    # Reject unknown fields instead of silently ignoring them.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: UUID
    user_id: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=100)
    # AwareDatetime rejects timestamps without a timezone.
    created_at: AwareDatetime


class MessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: UUID
    conversation_id: UUID
    seq: int = Field(ge=0)
    role: Role
    content: str = Field(min_length=1, max_length=20000)
    metadata: dict = Field(default_factory=dict)
    created_at: AwareDatetime