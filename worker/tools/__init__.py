"""Custom tools exposed to the Claude Agent SDK as in-process MCP servers."""

from worker.tools.mcp_proxy import create_mcp_proxy_servers
from worker.tools.memory import TOOL_NAMES as MEMORY_TOOL_NAMES
from worker.tools.memory import create_memory_server
from worker.tools.pipeline import TOOL_NAMES as PIPELINE_TOOL_NAMES
from worker.tools.pipeline import create_pipeline_server
from worker.tools.schedule import TOOL_NAMES as SCHEDULE_TOOL_NAMES
from worker.tools.schedule import create_schedule_server
from worker.tools.slack_thread import TOOL_NAMES as SLACK_THREAD_TOOL_NAMES
from worker.tools.slack_thread import create_slack_thread_server

TOOL_NAMES = [*SCHEDULE_TOOL_NAMES, *SLACK_THREAD_TOOL_NAMES, *MEMORY_TOOL_NAMES, *PIPELINE_TOOL_NAMES]

__all__ = [
    "TOOL_NAMES",
    "create_memory_server",
    "create_pipeline_server",
    "create_schedule_server",
    "create_slack_thread_server",
    "create_mcp_proxy_servers",
]
