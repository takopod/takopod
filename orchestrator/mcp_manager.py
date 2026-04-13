"""Host-side MCP server manager.

Manages MCP server processes on the host for a single agent session.
Communicates with each server via stdio using the ``mcp`` client library.
The worker container never needs MCP server packages installed -- it only
receives tool schemas and routes calls through file-based IPC.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

logger = logging.getLogger(__name__)

DEFAULT_TOOL_TIMEOUT = 30.0  # seconds


def _build_http_headers(config: dict[str, Any]) -> dict[str, str]:
    """Build HTTP headers from MCP server config, including auth."""
    headers: dict[str, str] = {}
    auth = config.get("auth", "none")
    env = config.get("env", {})

    if auth == "basic":
        username = env.get("MCP_USERNAME", "")
        token = env.get("MCP_API_TOKEN", "")
        if username and token:
            credentials = base64.b64encode(
                f"{username}:{token}".encode(),
            ).decode()
            headers["Authorization"] = f"Basic {credentials}"
        else:
            logger.warning(
                "Basic auth configured but MCP_USERNAME or MCP_API_TOKEN "
                "missing from env",
            )

    return headers


class _ServerConnection:
    """A long-lived connection to a single MCP server process.

    The MCP stdio_client and ClientSession use anyio task groups that
    must be entered and exited in the same asyncio task.  We run the
    entire lifecycle in a dedicated background task and communicate
    via an asyncio.Event for shutdown.
    """

    def __init__(self, name: str, timeout: float = DEFAULT_TOOL_TIMEOUT):
        self.name = name
        self.timeout = timeout
        self.session: ClientSession | None = None
        self._shutdown_event = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._ready_event = asyncio.Event()
        self._start_error: BaseException | None = None

    async def start(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self._task = asyncio.create_task(
            self._run(command, args or [], env),
            name=f"mcp-server-{self.name}",
        )
        await self._ready_event.wait()
        if self._start_error is not None:
            raise self._start_error

    async def start_http(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._task = asyncio.create_task(
            self._run_http(url, headers, http_client),
            name=f"mcp-server-{self.name}",
        )
        await self._ready_event.wait()
        if self._start_error is not None:
            raise self._start_error

    async def _run(
        self,
        command: str,
        args: list[str],
        env: dict[str, str] | None,
    ) -> None:
        """Background task that owns the stdio MCP context managers."""
        # Merge user-provided env with parent environment so the
        # subprocess retains PATH, HOME, etc. needed to run commands.
        merged_env = {**os.environ, **(env or {})}
        params = StdioServerParameters(
            command=command, args=args, env=merged_env,
        )
        try:
            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    self.session = session
                    logger.info(
                        "MCP server '%s' initialized (command=%s)",
                        self.name, command,
                    )
                    self._ready_event.set()
                    await self._shutdown_event.wait()
        except Exception as exc:
            self._start_error = exc
            self._ready_event.set()
        finally:
            self.session = None

    async def _run_http(
        self,
        url: str,
        headers: dict[str, str] | None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """Background task that owns the HTTP MCP context managers."""
        if http_client is None:
            http_client = httpx.AsyncClient(
                headers=headers or {},
                timeout=httpx.Timeout(30.0, read=300.0),
            )
        try:
            async with http_client:
                async with streamable_http_client(
                    url, http_client=http_client,
                ) as (read_stream, write_stream, _get_session_id):
                    async with ClientSession(
                        read_stream, write_stream,
                    ) as session:
                        await session.initialize()
                        self.session = session
                        logger.info(
                            "MCP server '%s' initialized (url=%s)",
                            self.name, url,
                        )
                        self._ready_event.set()
                        await self._shutdown_event.wait()
        except Exception as exc:
            self._start_error = exc
            self._ready_event.set()
        finally:
            self.session = None

    async def close(self) -> None:
        self._shutdown_event.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning(
                    "MCP server '%s' did not shut down in time, cancelling",
                    self.name,
                )
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            except Exception:
                logger.exception("Error closing MCP server '%s'", self.name)
            self._task = None


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
            transport = config.get("transport", "stdio")
            timeout = float(config.get("timeout", DEFAULT_TOOL_TIMEOUT))

            conn = _ServerConnection(name, timeout=timeout)
            try:
                if transport == "http":
                    url = config.get("url", "")
                    if not url:
                        logger.warning(
                            "MCP server '%s' has no url, skipping", name,
                        )
                        continue
                    auth = config.get("auth", "none")
                    if auth == "oauth":
                        from orchestrator.oauth import get_oauth_provider
                        provider = get_oauth_provider(name, url)
                        client = httpx.AsyncClient(
                            auth=provider,
                            timeout=httpx.Timeout(30.0, read=300.0),
                        )
                        await conn.start_http(url, http_client=client)
                    else:
                        headers = _build_http_headers(config)
                        await conn.start_http(url, headers)
                else:
                    command = config.get("command", "")
                    if not command:
                        logger.warning(
                            "MCP server '%s' has no command, skipping", name,
                        )
                        continue
                    args = config.get("args", [])
                    env = config.get("env") or None
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
