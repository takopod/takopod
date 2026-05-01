"""Pipeline builder — constructs the payload for the worker.

Resolves template variables in agent prompts and workflow prose,
then produces a PipelinePayload that can be injected into the
IPC message as plain JSON.
"""

from __future__ import annotations

import logging
from typing import Any

from orchestrator.pipelines.models import PipelineConfig, PipelinePayload
from orchestrator.pipelines.resolver import build_context, resolve

logger = logging.getLogger(__name__)


class PipelineBuilder:
    """Builds a PipelinePayload from a validated PipelineConfig."""

    def build(
        self,
        config: PipelineConfig,
        extracted_vars: dict[str, str],
    ) -> PipelinePayload:
        """Resolve templates and construct the worker payload.

        Args:
            config: Validated pipeline configuration.
            extracted_vars: Variables for template resolution
                            (e.g. {"run_id": "PROJQUAY-1234"}).

        Returns:
            PipelinePayload ready for IPC serialization.
        """
        run_id = extracted_vars.get("run_id", "unknown")

        # Resolve the artifacts directory template using the full resolver.
        # Build a minimal context first (without artifacts_dir itself),
        # resolve the directory template, then build the full context.
        profile_dict = config.profile.model_dump()
        pre_ctx = build_context(profile_dict, "", extracted_vars)
        artifacts_dir = resolve(config.workflow.artifacts.directory, pre_ctx)

        # Build the full template resolution context
        ctx = build_context(profile_dict, artifacts_dir, extracted_vars)

        # Resolve templates in all agent prompts
        resolved_agents: dict[str, dict[str, Any]] = {}
        for name, agent in config.agents.items():
            resolved_prompt = resolve(agent.prompt, ctx)
            agent_dict = agent.to_sdk_dict()
            agent_dict["prompt"] = resolved_prompt
            resolved_agents[name] = agent_dict

        # Resolve templates in the workflow prose (orchestrator instructions)
        resolved_prose = resolve(config.workflow_prose, ctx)

        # Inject phase metadata into the orchestrator prompt so it has
        # structured awareness of the pipeline phases alongside the prose
        phase_summary = self._build_phase_summary(config)
        system_prompt = (
            f"{resolved_prose}\n\n"
            f"## Pipeline Phase Reference\n\n"
            f"{phase_summary}"
        )

        return PipelinePayload(
            agents=resolved_agents,
            system_prompt=system_prompt,
            max_turns=config.workflow.orchestrator.max_turns,
            effort=config.workflow.orchestrator.effort,
            artifacts_dir=artifacts_dir,
            run_id=run_id,
            pipeline_name=config.workflow.name,
            project=config.profile.name,
        )

    def _build_phase_summary(self, config: PipelineConfig) -> str:
        """Build a structured summary of phases for the orchestrator prompt."""
        lines: list[str] = []
        lines.append("| Phase | Agent | Condition | Input | Output | Rework |")
        lines.append("|-------|-------|-----------|-------|--------|--------|")

        for phase in config.workflow.phases:
            agent = phase.agent or "(orchestrator)"
            condition = phase.condition or "always"
            inputs = ", ".join(phase.input) if phase.input else "-"
            rework = (
                f"{phase.rework.agent} (max {phase.rework.max})"
                if phase.rework
                else "-"
            )
            lines.append(
                f"| {phase.name} | {agent} | {condition} | "
                f"{inputs} | {phase.output} | {rework} |"
            )

        return "\n".join(lines)
