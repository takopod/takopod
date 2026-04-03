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


class CreateAgentRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    agent_type: str = "default"


class AgentResponse(BaseModel):
    id: str
    name: str
    agent_type: str
    status: str
    created_at: str


class AgentDetailResponse(AgentResponse):
    claude_md: str
    soul_md: str
    memory_md: str


class UpdateAgentRequest(BaseModel):
    claude_md: str | None = None
    soul_md: str | None = None
    memory_md: str | None = None
