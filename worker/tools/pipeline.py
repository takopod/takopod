"""Pipeline trigger tool — kicks off multi-agent pipeline workflows.

Thin MCP tool that writes a synchronous IPC request to the orchestrator
and returns the result. The orchestrator owns config loading and payload building.
"""

import json
import logging
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from worker.tools.ipc import ipc_request

logger = logging.getLogger(__name__)

TOOL_NAMES = [
    "mcp__pipeline__trigger_pipeline",
]

PIPELINE_TRIGGER_TIMEOUT = 30.0


def create_pipeline_server():
    """Build an in-process MCP server with the pipeline trigger tool."""

    @tool(
        "trigger_pipeline",
        "Trigger a multi-agent pipeline workflow for a project. "
        "The orchestrator validates the config, builds the payload, "
        "and queues a new pipeline message.",
        {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Pipeline skill name (e.g. quay-pipeline)",
                },
                "workflow": {
                    "type": "string",
                    "description": "Workflow name (e.g. bugfix, feature)",
                },
                "run_id": {
                    "type": "string",
                    "description": "JIRA ticket key (e.g. PROJQUAY-1234)",
                },
            },
            "required": ["project", "workflow", "run_id"],
        },
    )
    async def trigger_pipeline(args: dict[str, Any]) -> dict[str, Any]:
        params = {
            "project": args["project"],
            "workflow": args["workflow"],
            "run_id": args["run_id"],
        }
        try:
            data = await ipc_request(
                "pipeline_trigger", params, timeout=PIPELINE_TRIGGER_TIMEOUT,
            )
            run_id = data.get("run_id", args["run_id"])
            msg = f"Pipeline triggered successfully: {args['workflow']} workflow for {run_id}"
            logger.info(msg)
            return {"content": [{"type": "text", "text": msg}]}
        except RuntimeError as e:
            msg = f"Pipeline trigger failed: {e}"
            logger.error(msg)
            return {"content": [{"type": "text", "text": msg}]}

    return create_sdk_mcp_server(
        name="pipeline", version="1.0.0", tools=[trigger_pipeline],
    )
