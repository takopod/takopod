"""Pipeline configuration loader and validator.

Discovers, parses, and validates user-provided pipeline configs
from a skill directory (e.g. .claude/skills/quay-pipeline/).
The loader is scoped to a single project — the base directory
IS the project root.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from orchestrator.pipelines.models import (
    AgentConfig,
    PipelineConfig,
    ProfileConfig,
    WorkflowFrontmatter,
)

logger = logging.getLogger(__name__)


class PipelineLoadError(Exception):
    """Raised when pipeline config is invalid or cannot be loaded."""


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a markdown file into YAML frontmatter dict and prose body.

    Expects the file to start with '---', followed by YAML, then '---',
    then the markdown body.
    """
    text = text.strip()
    if not text.startswith("---"):
        raise PipelineLoadError(
            "File must start with '---' YAML frontmatter delimiter"
        )

    # Find closing delimiter on its own line
    rest = text[3:]
    match = re.search(r"\n---\s*\n", rest)
    if match is None:
        # Handle case where --- is at the very end of the file
        if rest.rstrip().endswith("\n---") or rest.rstrip() == "---":
            match = re.search(r"\n---\s*$", rest)
    if match is None:
        raise PipelineLoadError(
            "Missing closing '---' delimiter for YAML frontmatter"
        )

    yaml_str = rest[: match.start()].strip()
    body = rest[match.end() :].strip()

    try:
        frontmatter = yaml.safe_load(yaml_str) or {}
    except yaml.YAMLError as e:
        raise PipelineLoadError(f"Invalid YAML in frontmatter: {e}") from e

    if not isinstance(frontmatter, dict):
        raise PipelineLoadError("Frontmatter must be a YAML mapping")

    return frontmatter, body


class PipelineLoader:
    """Loads pipeline configurations from a skill directory.

    The base_dir is the skill directory root (e.g. .claude/skills/quay-pipeline/).
    It contains profile.yaml, workflow .md files, and an agents/ subdirectory.
    """

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir

    def discover_workflows(self) -> list[str]:
        """List all workflow files (without .md extension)."""
        if not self.base_dir.is_dir():
            return []
        return sorted(
            f.stem
            for f in self.base_dir.iterdir()
            if f.is_file()
            and f.suffix == ".md"
            and f.stem not in ("README", "SKILL")
        )

    def load_agents(self) -> dict[str, AgentConfig]:
        """Load all agent definitions from agents/ subdirectory."""
        agents_dir = self.base_dir / "agents"
        if not agents_dir.is_dir():
            raise PipelineLoadError(
                f"No agents/ directory found at {agents_dir}"
            )

        agents: dict[str, AgentConfig] = {}
        for agent_file in sorted(agents_dir.glob("*.md")):
            name = agent_file.stem
            try:
                text = agent_file.read_text()
                frontmatter, body = _split_frontmatter(text)
                frontmatter["prompt"] = body
                agents[name] = AgentConfig(**frontmatter)
            except (PipelineLoadError, ValidationError) as e:
                raise PipelineLoadError(
                    f"Invalid agent definition '{name}' at {agent_file}: {e}"
                ) from e

        if not agents:
            raise PipelineLoadError(
                f"No agent .md files found in {agents_dir}"
            )

        return agents

    def load_profile(self) -> ProfileConfig:
        """Load the project profile from profile.yaml."""
        profile_path = self.base_dir / "profile.yaml"
        if not profile_path.is_file():
            raise PipelineLoadError(
                f"No profile.yaml found at {profile_path}"
            )

        try:
            data = yaml.safe_load(profile_path.read_text()) or {}
        except yaml.YAMLError as e:
            raise PipelineLoadError(
                f"Invalid YAML in {profile_path}: {e}"
            ) from e

        try:
            return ProfileConfig(**data)
        except ValidationError as e:
            raise PipelineLoadError(
                f"Invalid profile at {profile_path}: {e}"
            ) from e

    def load_workflow(self, workflow: str) -> tuple[WorkflowFrontmatter, str]:
        """Load a workflow definition.

        Returns (parsed_frontmatter, prose_body).
        """
        workflow_path = self.base_dir / f"{workflow}.md"
        if not workflow_path.is_file():
            raise PipelineLoadError(
                f"Workflow file not found: {workflow_path}"
            )

        try:
            text = workflow_path.read_text()
            frontmatter, prose = _split_frontmatter(text)
        except PipelineLoadError as e:
            raise PipelineLoadError(
                f"Error parsing {workflow_path}: {e}"
            ) from e

        try:
            parsed = WorkflowFrontmatter(**frontmatter)
        except ValidationError as e:
            raise PipelineLoadError(
                f"Invalid workflow frontmatter in {workflow_path}: {e}"
            ) from e

        return parsed, prose

    def load_pipeline(self, workflow: str) -> PipelineConfig:
        """Load and validate a complete pipeline configuration.

        Loads agents, profile, and workflow, then validates structural
        integrity (agent references, phase DAG).
        """
        agents = self.load_agents()
        profile = self.load_profile()
        wf_frontmatter, wf_prose = self.load_workflow(workflow)

        config = PipelineConfig(
            agents=agents,
            workflow=wf_frontmatter,
            workflow_prose=wf_prose,
            profile=profile,
        )

        self._validate(config)
        return config

    def _validate(self, config: PipelineConfig) -> None:
        """Validate structural integrity of a pipeline config."""
        errors: list[str] = []
        available_agents = set(config.agents.keys())

        # Check required agents exist
        for name in config.workflow.agents.required:
            if name not in available_agents:
                errors.append(
                    f"Required agent '{name}' not found in agents/. "
                    f"Available: {sorted(available_agents)}"
                )

        # Check optional agents exist
        for name in config.workflow.agents.optional:
            if name not in available_agents:
                errors.append(
                    f"Optional agent '{name}' not found in agents/. "
                    f"Available: {sorted(available_agents)}"
                )

        # Check phase agent references
        for phase in config.workflow.phases:
            if phase.agent and phase.agent not in available_agents:
                errors.append(
                    f"Phase '{phase.name}' references agent '{phase.agent}' "
                    f"which is not defined in agents/"
                )

            if phase.rework:
                if phase.rework.agent not in available_agents:
                    errors.append(
                        f"Phase '{phase.name}' rework references agent "
                        f"'{phase.rework.agent}' which is not defined"
                    )
                if phase.rework.max < 1:
                    errors.append(
                        f"Phase '{phase.name}' rework max must be >= 1"
                    )

        # Check phase input/output DAG — inputs must come from earlier outputs
        produced_outputs: set[str] = set()
        for phase in config.workflow.phases:
            for inp in phase.input:
                if inp not in produced_outputs:
                    errors.append(
                        f"Phase '{phase.name}' requires input '{inp}' but "
                        f"no earlier phase produces it. "
                        f"Available: {sorted(produced_outputs) or '(none)'}"
                    )
            if phase.output in produced_outputs:
                errors.append(
                    f"Phase '{phase.name}' output '{phase.output}' is "
                    f"already produced by an earlier phase"
                )
            produced_outputs.add(phase.output)

        if errors:
            msg = f"Pipeline validation failed with {len(errors)} error(s):\n"
            msg += "\n".join(f"  - {e}" for e in errors)
            raise PipelineLoadError(msg)
