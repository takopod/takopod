"""Host-side MCP server manager.

Manages MCP server processes on the host for a single agent session.
Communicates with each server via stdio using the ``mcp`` client library.
The worker container never needs MCP server packages installed -- it only
receives tool schemas and routes calls through file-based IPC.
"""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

logger = logging.getLogger(__name__)

DEFAULT_TOOL_TIMEOUT = 30.0  # seconds


class _ServerConnection:
    """A long-lived connection to a single MCP server process."""

    def __init__(self, name: str, timeout: float = DEFAULT_TOOL_TIMEOUT):
        self.name = name
        self.timeout = timeout
        self.session: ClientSession | None = None
        self._stack = AsyncExitStack()

    async def start(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        params = StdioServerParameters(
            command=command,
            args=args or [],
            env=env if env else None,
        )
        read_stream, write_stream = await self._stack.enter_async_context(
            stdio_client(params),
        )
        self.session = await self._stack.enter_async_context(
            ClientSession(read_stream, write_stream),
        )
        await self.session.initialize()
        logger.info("MCP server '%s' initialized (command=%s)", self.name, command)

    async def close(self) -> None:
        try:
            await self._stack.aclose()
        except Exception:
            logger.exception("Error closing MCP server '%s'", self.name)
        self.session = None


class McpServerManager:
    """Manages MCP server processes on the host for a single agent."""

    def __init__(self) -> None:
        self._servers: dict[str, _ServerConnection] = {}
        self._tool_to_server: dict[str, str] = {}
        self._tool_schemas: list[dict[str, Any]] = []

    async def start(self, mcp_config: dict[str, Any]) -> None:
        """Start all MCP servers defined in the config.

        ``mcp_config`` uses the standard ``.mcp.json`` format::

            {"mcpServers": {"name": {"command": "...", "args": [...], "env": {...}, "timeout": 30}}}
        """
        servers = mcp_config.get("mcpServers", {})
        for name, config in servers.items():
            command = config.get("command", "")
            if not command:
                logger.warning("MCP server '%s' has no command, skipping", name)
                continue

            args = config.get("args", [])
            env = config.get("env") or None
            timeout = float(config.get("timeout", DEFAULT_TOOL_TIMEOUT))

            conn = _ServerConnection(name, timeout=timeout)
            try:
                await conn.start(command, args, env)
            except Exception:
                logger.exception("Failed to start MCP server '%s'", name)
                await conn.close()
                continue

            self._servers[name] = conn

            # Discover tools from this server
            try:
                result = await conn.session.list_tools()
                for tool in result.tools:
                    self._tool_to_server[tool.name] = name
                    self._tool_schemas.append({
                        "name": tool.name,
                        "description": tool.description or "",
                        "input_schema": tool.inputSchema,
                        "server_name": name,
                        "timeout": timeout,
                    })
                logger.info(
                    "MCP server '%s': %d tools discovered", name, len(result.tools),
                )
            except Exception:
                logger.exception(
                    "Failed to list tools from MCP server '%s'", name,
                )

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Call a tool on the appropriate MCP server and return the result."""
        server_name = self._tool_to_server.get(tool_name)
        if not server_name:
            raise ValueError(f"Unknown MCP tool: {tool_name}")

        conn = self._servers.get(server_name)
        if not conn or not conn.session:
            raise RuntimeError(f"MCP server '{server_name}' is not connected")

        result = await conn.session.call_tool(tool_name, arguments)
        # Serialize MCP content blocks to dicts
        content = []
        for block in result.content:
            content.append(block.model_dump())
        return {"content": content, "isError": result.isError}

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """Return all tool schemas from all managed servers."""
        return list(self._tool_schemas)

    async def stop(self) -> None:
        """Stop all managed MCP server processes."""
        for name, conn in self._servers.items():
            logger.info("Stopping MCP server '%s'", name)
            await conn.close()
        self._servers.clear()
        self._tool_to_server.clear()
        self._tool_schemas.clear()
