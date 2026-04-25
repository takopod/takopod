"""MCP proxy — forwards external MCP tool calls to the orchestrator via IPC.

Reads tool schemas from /workspace/mcp_tools.json (written by the orchestrator)
and registers each tool as an in-process MCP tool.  When Claude calls any of
these tools, the proxy sends an ``mcp_call`` IPC request to the orchestrator,
which routes it to the actual MCP server running on the host.
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from claude_agent_sdk import create_sdk_mcp_server, tool

from worker.tools.ipc import ipc_request

MCP_TOOLS_PATH = Path("/workspace/mcp_tools.json")
DEFAULT_TIMEOUT = 30.0


def create_mcp_proxy_servers() -> list[tuple[str, Any, list[str]]]:
    """Build per-server MCP proxies for all external MCP tools.

    Groups tools by their ``server_name`` so each MCP server gets its own
    namespace (e.g. ``mcp__slack__list_channels`` instead of
    ``mcp__proxy__list_channels``).

    Returns a list of ``(server_name, mcp_server, tool_names)`` tuples — one
    per server.  Returns an empty list if no tools are configured.
    """
    if not MCP_TOOLS_PATH.is_file():
        return []

    try:
        schemas = json.loads(MCP_TOOLS_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return []

    if not schemas:
        return []

    # Group tool schemas by server_name
    by_server: dict[str, list[dict[str, Any]]] = {}
    for schema in schemas:
        server_name = schema.get("server_name", "proxy")
        by_server.setdefault(server_name, []).append(schema)

    results: list[tuple[str, Any, list[str]]] = []

    for server_name, server_schemas in by_server.items():
        tool_functions = []
        tool_names: list[str] = []

        for schema in server_schemas:
            name = schema["name"]
            description = schema.get("description", "")
            input_schema = schema.get("input_schema", {"type": "object", "properties": {}})
            timeout = float(schema.get("timeout", DEFAULT_TIMEOUT))

            @tool(name, description, input_schema)
            async def proxy_call(
                args: dict[str, Any],
                _name: str = name,
                _server: str = server_name,
                _timeout: float = timeout,
            ) -> dict[str, Any]:
                logger.debug("mcp_call %s/%s", _server, _name)
                data = await ipc_request(
                    "mcp_call",
                    {
                        "tool_name": _name,
                        "server_name": _server,
                        "arguments": args,
                    },
                    timeout=_timeout,
                )
                content = data.get("content", [])
                text_parts = []
                for block in content:
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    else:
                        text_parts.append(json.dumps(block))
                return {
                    "content": [{"type": "text", "text": "\n".join(text_parts)}],
                }

            tool_functions.append(proxy_call)
            tool_names.append(f"mcp__{server_name}__{name}")

        logger.info("mcp_proxy loaded %d tools for server '%s'", len(tool_functions), server_name)

        server = create_sdk_mcp_server(
            name=server_name,
            version="1.0.0",
            tools=tool_functions,
        )
        results.append((server_name, server, tool_names))

    return results
