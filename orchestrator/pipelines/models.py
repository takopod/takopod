"""Pydantic models for pipeline configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class AgentConfig(BaseModel):
    """Agent role definition parsed from an agent .md file."""

    description: str
    prompt: str
    model: str = "sonnet"
    maxTurns: int = 25
    tools: list[str] | None = None
    permissionMode: str = "acceptEdits"

    def to_sdk_dict(self) -> dict[str, Any]:
        """Convert to a dict suitable for AgentDefinition construction."""
        d: dict[str, Any] = {
            "description": self.description,
            "prompt": self.prompt,
            "model": self.model,
            "maxTurns": self.maxTurns,
            "permissionMode": self.permissionMode,
        }
        if self.tools is not None:
            d["tools"] = self.tools
        return d


class ReworkConfig(BaseModel):
    """Rework loop configuration for a pipeline phase."""

    agent: str
    max: int
    when: Literal["fail", "rework"]


class PhaseConfig(BaseModel):
    """A single phase in a pipeline workflow."""

    name: str
    agent: str | None = None
    condition: str | None = None
    input: list[str] = []
    output: str
    description: str | None = None
    rework: ReworkConfig | None = None


class TriggerConfig(BaseModel):
    """Message pattern that activates a pipeline."""

    pattern: str
    extract: str  # variable name for the first capture group


class AgentRoster(BaseModel):
    """Agents used by a workflow."""

    required: list[str]
    optional: list[str] = []


class ArtifactConfig(BaseModel):
    """Artifact directory configuration."""

    directory: str  # e.g. ".pipeline/{run_id}"
    status_file: str = "status.json"


class OrchestratorConfig(BaseModel):
    """Configuration for the orchestrator agent itself."""

    model: str = "sonnet"
    max_turns: int = 100
    effort: str = "high"


class WorkflowFrontmatter(BaseModel):
    """Parsed YAML frontmatter from a workflow .md file."""

    name: str
    description: str
    version: int = 1
    triggers: list[TriggerConfig]
    agents: AgentRoster
    phases: list[PhaseConfig]
    artifacts: ArtifactConfig
    orchestrator: OrchestratorConfig = OrchestratorConfig()


class ProfileConfig(BaseModel):
    """Project profile — arbitrary key-value pairs for template resolution."""

    model_config = ConfigDict(extra="allow")

    name: str
    description: str


class PipelineConfig(BaseModel):
    """Complete validated pipeline configuration."""

    agents: dict[str, AgentConfig]
    workflow: WorkflowFrontmatter
    workflow_prose: str
    profile: ProfileConfig


@dataclass
class PipelinePayload:
    """Data injected into the worker message to run a pipeline.

    All fields are JSON-serializable (no SDK objects).
    """

    agents: dict[str, dict[str, Any]]
    system_prompt: str
    max_turns: int
    effort: str | None
    artifacts_dir: str
    run_id: str
    pipeline_name: str
    project: str

    def to_message_fields(self) -> dict[str, Any]:
        """Return fields to merge into the IPC message payload."""
        fields: dict[str, Any] = {
            "pipeline_agents": self.agents,
            "pipeline_system_prompt": self.system_prompt,
            "pipeline_max_turns": self.max_turns,
            "pipeline_artifacts_dir": self.artifacts_dir,
            "pipeline_run_id": self.run_id,
            "pipeline_name": self.pipeline_name,
            "pipeline_project": self.project,
        }
        if self.effort:
            fields["pipeline_effort"] = self.effort
        return fields
