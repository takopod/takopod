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


class StatusFrame(BaseModel):
    type: Literal["status"] = "status"
    status: Literal[
        "thinking", "generating", "done", "error", "idle", "context_cleared"
    ]
    message_id: str


class CreateAgentRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    agent_type: str = "default"


class AgentResponse(BaseModel):
    id: str
    name: str
    agent_type: str
    status: str
    created_at: str
    container_status: str | None = None
    active_session_count: int = 0


class AgentDetailResponse(AgentResponse):
    claude_md: str
    soul_md: str
    memory_md: str


class UpdateAgentRequest(BaseModel):
    claude_md: str | None = None
    soul_md: str | None = None
    memory_md: str | None = None


class SystemErrorFrame(BaseModel):
    type: Literal["system_error"] = "system_error"
    error: str
    fatal: bool = False


class SystemCommandFrame(BaseModel):
    type: Literal["system_command"]
    command: Literal["clear_context", "shutdown"]


class FileEntry(BaseModel):
    name: str
    path: str
    type: Literal["file", "directory"]
    size: int | None = None
    modified_at: str | None = None


class ContainerResponse(BaseModel):
    id: str
    agent_id: str
    agent_name: str | None = None
    session_id: str | None = None
    container_type: str
    status: str
    started_at: str
    stopped_at: str | None = None
    last_activity: str
    pid: int | None = None


class ScheduleResponse(BaseModel):
    id: str
    agent_id: str
    agent_name: str
    prompt: str
    allowed_tools: list[str]
    interval_seconds: int
    last_executed_at: str | None
    last_result: str | None
    status: str
    created_at: str
