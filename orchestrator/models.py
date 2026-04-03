from typing import Literal

from pydantic import BaseModel, Field


class UserMessageFrame(BaseModel):
    type: Literal["user_message"]
    content: str = Field(..., min_length=1, max_length=10_000)
    message_id: str


class QueueStatusFrame(BaseModel):
    type: Literal["queue_status"] = "queue_status"
    queued: int
    in_flight: int
    processed: int


class ErrorFrame(BaseModel):
    type: Literal["error"] = "error"
    code: Literal["RATE_LIMITED", "QUEUE_FULL"]
    retry_after_seconds: float | None = None


class TokenFrame(BaseModel):
    type: Literal["token"] = "token"
    content: str
    message_id: str
    seq: int


class StatusFrame(BaseModel):
    type: Literal["status"] = "status"
    status: Literal[
        "thinking", "generating", "done", "error", "idle", "context_cleared"
    ]
    message_id: str


class CompleteFrame(BaseModel):
    type: Literal["complete"] = "complete"
    content: str
    message_id: str
    usage: dict | None = None
