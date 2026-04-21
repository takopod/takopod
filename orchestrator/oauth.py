"""OAuth flow management and file-backed token storage for HTTP MCP servers."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import httpx
from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

logger = logging.getLogger(__name__)

OAUTH_TOKENS_DIR = Path("data/oauth-tokens")
REDIRECT_URI = "http://localhost:8000/oauth/callback"


class FileTokenStorage:
    """Persist OAuth tokens and client info to a JSON file on disk."""

    def __init__(self, server_name: str) -> None:
        self._path = OAUTH_TOKENS_DIR / f"{server_name}.json"

    def _read(self) -> dict[str, Any]:
        if not self._path.is_file():
            return {}
        try:
            return json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def _write(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2))

    async def get_tokens(self) -> OAuthToken | None:
        data = self._read()
        tokens = data.get("tokens")
        if tokens:
            return OAuthToken(**tokens)
        return None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        data = self._read()
        data["tokens"] = json.loads(tokens.model_dump_json(exclude_none=True))
        self._write(data)

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        data = self._read()
        client_info = data.get("client_info")
        if client_info:
            return OAuthClientInformationFull(**client_info)
        return None

    async def set_client_info(
        self, client_info: OAuthClientInformationFull,
    ) -> None:
        data = self._read()
        data["client_info"] = json.loads(
            client_info.model_dump_json(exclude_none=True),
        )
        self._write(data)

    def has_tokens(self) -> bool:
        data = self._read()
        return bool(data.get("tokens", {}).get("access_token"))

    def delete(self) -> None:
        if self._path.is_file():
            self._path.unlink()


class OAuthFlowManager:
    """Bridges OAuthClientProvider's redirect/callback handlers with HTTP endpoints.

    The OAuth flow works like this:
    1. Frontend calls /oauth/start/{server_name}
    2. We create an OAuthClientProvider and trigger the flow by making a
       dummy request to the MCP server (which returns 401)
    3. The provider calls redirect_handler with the authorization URL
    4. We return that URL to the frontend, which opens it in a browser tab
    5. User consents, Atlassian redirects to /oauth/callback?code=...&state=...
    6. The callback endpoint calls complete_flow(code, state)
    7. This resolves the Future that callback_handler is awaiting
    8. The provider exchanges the code for tokens and stores them
    """

    def __init__(self) -> None:
        # Maps state -> Future that will be resolved with (code, state)
        self._pending: dict[str, asyncio.Future[tuple[str, str | None]]] = {}
        # Maps state -> server_name (for logging/cleanup)
        self._state_to_server: dict[str, str] = {}
        # Stores the authorize URL captured from redirect_handler
        self._authorize_url: str | None = None

    async def start_flow(
        self, server_name: str, server_url: str,
    ) -> str:
        """Initiate an OAuth flow. Returns the authorization URL."""
        storage = FileTokenStorage(server_name)
        self._authorize_url = None

        # Future that callback_handler will await
        callback_future: asyncio.Future[tuple[str, str | None]] = (
            asyncio.get_event_loop().create_future()
        )

        async def redirect_handler(url: str) -> None:
            """Called by OAuthClientProvider with the authorization URL."""
            self._authorize_url = url
            # Extract state from the URL to index the pending flow
            from urllib.parse import parse_qs, urlparse
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            state = params.get("state", [None])[0]
            if state:
                self._pending[state] = callback_future
                self._state_to_server[state] = server_name

        async def callback_handler() -> tuple[str, str | None]:
            """Called by OAuthClientProvider; blocks until callback endpoint resolves."""
            return await callback_future

        provider = OAuthClientProvider(
            server_url=server_url,
            client_metadata=OAuthClientMetadata(
                redirect_uris=[REDIRECT_URI],
                client_name="takopod",
                grant_types=["authorization_code", "refresh_token"],
                response_types=["code"],
            ),
            storage=storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
        )

        # Trigger the OAuth flow by making a request to the MCP server.
        # The provider's auth_flow will get a 401 and start the OAuth dance.
        # We run this in a background task because it will block on
        # callback_handler until complete_flow is called.
        flow_error: list[str] = []

        async def _run_flow() -> None:
            try:
                async with httpx.AsyncClient(auth=provider) as client:
                    resp = await client.get(server_url)
                    logger.info(
                        "OAuth trigger request for '%s' returned %d",
                        server_name, resp.status_code,
                    )
            except Exception as exc:
                msg = f"OAuth flow failed for server '{server_name}': {exc}"
                logger.exception(msg)
                flow_error.append(str(exc))
                # Clean up pending futures
                for state, srv in list(self._state_to_server.items()):
                    if srv == server_name and state in self._pending:
                        fut = self._pending.pop(state)
                        self._state_to_server.pop(state, None)
                        if not fut.done():
                            fut.cancel()

        asyncio.create_task(
            _run_flow(), name=f"oauth-flow-{server_name}",
        )

        # Wait for redirect_handler to be called. The auth flow needs to:
        # 1. Make the initial request (401)
        # 2. Discover protected resource metadata
        # 3. Discover OAuth metadata
        # 4. Register the client (dynamic client registration)
        # 5. Build the authorization URL and call redirect_handler
        # This can take a while, so allow up to 30 seconds.
        for _ in range(300):
            if self._authorize_url is not None:
                break
            if flow_error:
                raise RuntimeError(flow_error[0])
            await asyncio.sleep(0.1)

        if self._authorize_url is None:
            detail = flow_error[0] if flow_error else (
                "did not produce an authorization URL within 30 seconds"
            )
            raise RuntimeError(
                f"OAuth flow for '{server_name}': {detail}",
            )

        url = self._authorize_url
        self._authorize_url = None
        return url

    def complete_flow(self, code: str, state: str) -> str | None:
        """Called by the callback endpoint. Returns server_name or None."""
        future = self._pending.pop(state, None)
        server_name = self._state_to_server.pop(state, None)
        if future and not future.done():
            future.set_result((code, state))
            logger.info(
                "OAuth flow completed for server '%s'", server_name,
            )
        return server_name


# Singleton flow manager
flow_manager = OAuthFlowManager()


def get_oauth_provider(
    server_name: str, server_url: str,
) -> OAuthClientProvider:
    """Create an OAuthClientProvider using stored tokens.

    Used by mcp_manager when starting an HTTP MCP server with oauth auth.
    If valid tokens exist, no browser interaction is needed.
    """
    storage = FileTokenStorage(server_name)
    return OAuthClientProvider(
        server_url=server_url,
        client_metadata=OAuthClientMetadata(
            redirect_uris=[REDIRECT_URI],
            client_name="takopod",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        ),
        storage=storage,
        # No redirect/callback handlers — if tokens are stored and valid,
        # the provider will use them directly. If they need refresh, the
        # provider handles that automatically. If no tokens exist at all,
        # the connection will fail with an error indicating auth is needed.
    )
