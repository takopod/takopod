"""Custom tools exposed to the Claude Agent SDK as in-process MCP servers."""

from worker.tools.mcp_proxy import create_mcp_proxy_servers
from worker.tools.schedule import TOOL_NAMES as SCHEDULE_TOOL_NAMES
from worker.tools.schedule import create_schedule_server
from worker.tools.slack_thread import TOOL_NAMES as SLACK_THREAD_TOOL_NAMES
from worker.tools.slack_thread import create_slack_thread_server

TOOL_NAMES = [*SCHEDULE_TOOL_NAMES, *SLACK_THREAD_TOOL_NAMES]

__all__ = [
    "TOOL_NAMES",
    "create_schedule_server",
    "create_slack_thread_server",
    "create_mcp_proxy_servers",
]
