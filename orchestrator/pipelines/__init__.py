"""Generic pipeline engine for multi-agent workflow orchestration."""

from orchestrator.pipelines.builder import PipelineBuilder
from orchestrator.pipelines.loader import PipelineLoader
from orchestrator.pipelines.trigger import TriggerDetector

__all__ = ["PipelineLoader", "TriggerDetector", "PipelineBuilder"]
