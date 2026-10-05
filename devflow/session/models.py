from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class SessionEntry(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    parent_id: str | None
    session_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    type: Literal[
        "user_message",
        "assistant_message",
        "tool_call",
        "tool_result",
        "compaction",
        "branch_summary",
        "todo_snapshot",
        "session_meta",
        "recovery",
        "turn_end",
    ]
    payload: dict
