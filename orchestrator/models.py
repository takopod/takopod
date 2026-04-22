import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


def _validate_memory(v: str) -> str:
    """Validate Podman memory format: number followed by b/k/m/g (e.g. '512m', '2g')."""
    if not re.fullmatch(r"\d+[bkmg]", v, re.IGNORECASE):
        raise ValueError("Memory must be a number followed by b/k/m/g (e.g. '512m', '2g')")
    return v.lower()


def _validate_cpus(v: str) -> str:
    """Validate Podman CPU value: positive number (e.g. '2', '1.5', '0.5')."""
    try:
        val = float(v)
    except ValueError:
        raise ValueError("CPUs must be a positive number (e.g. '2', '1.5')")
    if val <= 0:
        raise ValueError("CPUs must be greater than 0")
    # Normalize: drop trailing .0 for whole numbers
    return str(int(val)) if val == int(val) else str(val)



class UserMessageFrame(BaseModel):
    type: Literal["user_message"]
    content: str = Field(..., min_length=1, max_length=10_000)
    message_id: str
    attachments: list[str] = []  # relative paths within workspace (e.g. "uploads/abc/file.png")


class QueueStatusFrame(BaseModel):
    type: Literal["queue_status"] = "queue_status"
    queued: int
    in_flight: int


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


class AgentResponse(BaseModel):
    id: str
    name: str
    icon: str = ""
    status: str
    created_at: str
    container_status: str | None = None
    container_memory: str = "2g"
    container_cpus: str = "2"


class AgentDetailResponse(AgentResponse):
    pass


class UpdateAgentRequest(BaseModel):
    container_memory: str | None = None
    container_cpus: str | None = None

    @field_validator("container_memory")
    @classmethod
    def validate_memory(cls, v: str | None) -> str | None:
        return _validate_memory(v) if v is not None else None

    @field_validator("container_cpus")
    @classmethod
    def validate_cpus(cls, v: str | None) -> str | None:
        return _validate_cpus(v) if v is not None else None


class SystemErrorFrame(BaseModel):
    type: Literal["system_error"] = "system_error"
    error: str
    fatal: bool = False


class SystemCommandFrame(BaseModel):
    type: Literal["system_command"]
    command: Literal["clear_context", "shutdown"]


class GhApprovalRequestFrame(BaseModel):
    type: Literal["gh_approval_request"] = "gh_approval_request"
    request_id: str
    agent_id: str
    command: str
    message_id: str
    timestamp: str


class GhApprovalResponseFrame(BaseModel):
    type: Literal["gh_approval_response"]
    request_id: str
    approved: bool


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
    container_type: str
    status: str
    started_at: str
    stopped_at: str | None = None
    last_activity: str
    pid: int | None = None


class McpServerResponse(BaseModel):
    id: str
    name: str
    transport: str = "stdio"
    command: str = ""
    args: list[str] = []
    url: str = ""
    auth: str = "none"
    env: dict[str, str] = {}
    timeout: float = 30.0
    builtin: bool = False
    note: str = ""
    display_name: str = ""


class CreateMcpServerRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    transport: Literal["stdio", "http"] = "stdio"
    command: str = ""
    args: list[str] = []
    url: str = ""
    auth: Literal["none", "basic", "oauth"] = "none"
    env: dict[str, str] = {}
    timeout: float = 30.0

    @model_validator(mode="after")
    def validate_transport_fields(self):
        if self.transport == "stdio" and not self.command:
            raise ValueError("'command' is required for stdio transport")
        if self.transport == "http" and not self.url:
            raise ValueError("'url' is required for http transport")
        return self


class UpdateMcpServerRequest(BaseModel):
    transport: Literal["stdio", "http"] | None = None
    command: str | None = None
    args: list[str] | None = None
    url: str | None = None
    auth: Literal["none", "basic", "oauth"] | None = None
    env: dict[str, str] | None = None
    timeout: float | None = None


class ToolConfigRequest(BaseModel):
    builtin: list[str]
    permission_mode: str = "acceptEdits"


class CreateSkillRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9-]*$")
    description: str = ""
    content: str = ""


class UpdateSkillRequest(BaseModel):
    content: str


class SkillSummary(BaseModel):
    id: str
    name: str
    description: str
    builtin: bool = False


class SkillDetail(SkillSummary):
    content: str
    files: list[str] = []


class SkillDraftSummary(BaseModel):
    id: str
    name: str
    description: str
    files: list[str] = []


class SkillDraftDetail(BaseModel):
    id: str
    name: str
    description: str
    content: str
    files: list[str] = []


class RegistrySkillSummary(BaseModel):
    id: str
    name: str
    description: str
    builtin: bool = False
    always_enabled: bool = False


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


class SlackConfigRequest(BaseModel):
    xoxc_token: str
    d_cookie: str
    member_id: str


class SlackAgentToggle(BaseModel):
    enabled: bool


class SlackPollingToggle(BaseModel):
    enabled: bool


class SlackPollingChannelRequest(BaseModel):
    channel_id: str = Field(..., min_length=1)
    channel_name: str = ""
    interval_seconds: int = Field(30, ge=10, le=300)


class SlackPollingChannelUpdate(BaseModel):
    interval_seconds: int | None = Field(None, ge=10, le=300)
    enabled: bool | None = None


class SlackThreadRequest(BaseModel):
    channel_id: str = Field(..., min_length=1)
    thread_ts: str = Field(..., min_length=1)
    agent_id: str = Field(..., min_length=1)



# --- Search Index ---


class SearchIndexEntry(BaseModel):
    chunk_key: str
    content: str
    file_path: str
    session_ref: str
    created_at: str
    rank: float = 0.0
    has_embedding: bool = False


class SearchIndexStats(BaseModel):
    memory_files_count: int
    fts_count: int
    vec_count: int


class SearchIndexUpdateRequest(BaseModel):
    content: str = Field(..., min_length=1)


class ReindexRequest(BaseModel):
    chunk_keys: list[str] | None = None


class ReindexResponse(BaseModel):
    indexed: int
    errors: int
    skipped_vectors: bool


class MemoryFileEntry(BaseModel):
    name: str
    size: int
    modified_at: str
    content_preview: str
    content: str


