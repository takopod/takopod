"""Pipeline trigger detection.

Scans incoming messages against compiled trigger patterns
from all registered pipeline workflows.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from orchestrator.pipelines.loader import PipelineLoadError, PipelineLoader

logger = logging.getLogger(__name__)


@dataclass
class TriggerMatch:
    """Result of a successful trigger detection."""

    project: str
    workflow: str
    extracted_vars: dict[str, str]


@dataclass
class _CompiledTrigger:
    project: str
    workflow: str
    pattern: re.Pattern[str]
    extract_name: str


class TriggerDetector:
    """Detects pipeline triggers in incoming messages."""

    def __init__(self, loader: PipelineLoader):
        self.loader = loader
        self._triggers: list[_CompiledTrigger] = []

    def refresh(self) -> None:
        """Scan all projects/workflows and compile trigger patterns.

        Call on startup and when pipeline configs change.
        """
        triggers: list[_CompiledTrigger] = []

        for project in self.loader.discover_projects():
            for workflow in self.loader.discover_workflows(project):
                try:
                    wf_frontmatter, _ = self.loader.load_workflow(
                        project, workflow
                    )
                except PipelineLoadError as e:
                    logger.warning(
                        "Skipping triggers for %s/%s: %s",
                        project, workflow, e,
                    )
                    continue

                for trigger_cfg in wf_frontmatter.triggers:
                    try:
                        compiled = re.compile(
                            trigger_cfg.pattern, re.IGNORECASE
                        )
                    except re.error as e:
                        logger.warning(
                            "Invalid trigger pattern in %s/%s: %s",
                            project, workflow, e,
                        )
                        continue

                    triggers.append(
                        _CompiledTrigger(
                            project=project,
                            workflow=workflow,
                            pattern=compiled,
                            extract_name=trigger_cfg.extract,
                        )
                    )

        self._triggers = triggers
        logger.info(
            "Loaded %d pipeline trigger(s) from %d project(s)",
            len(triggers),
            len(self.loader.discover_projects()),
        )

    def detect(self, message: str) -> TriggerMatch | None:
        """Match a message against all registered triggers.

        Returns the first match, preferring longer pattern matches
        when multiple triggers match.

        Returns None if no trigger matches.
        """
        message = message.strip()
        if not message:
            return None

        best_match: TriggerMatch | None = None
        best_match_len = -1

        for trigger in self._triggers:
            m = trigger.pattern.search(message)
            if m:
                match_len = m.end() - m.start()
                if match_len > best_match_len:
                    extracted_value = m.group(1) if m.lastindex else m.group(0)
                    best_match = TriggerMatch(
                        project=trigger.project,
                        workflow=trigger.workflow,
                        extracted_vars={
                            trigger.extract_name: extracted_value,
                        },
                    )
                    best_match_len = match_len

        return best_match
