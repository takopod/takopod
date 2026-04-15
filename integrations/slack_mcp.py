"""Slack MCP server for rhclaw.

Provides tools to read Slack channels and send messages to yourself.
Runs on the host (orchestrator) side — credentials never enter worker containers.

Usage (standalone testing):
    SLACK_XOXC_TOKEN=xoxc-... SLACK_D_COOKIE=xoxd-... MY_MEMBER_ID=U01234567 \
        python -m integrations.slack_mcp
"""

from __future__ import annotations

import os
import re

from mcp.server.fastmcp import FastMCP
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

mcp = FastMCP("SlackIntegration")

SLACK_TOKEN = os.environ.get("SLACK_XOXC_TOKEN", "")
SLACK_COOKIE = os.environ.get("SLACK_D_COOKIE", "")
MY_MEMBER_ID = os.environ.get("MY_MEMBER_ID", "")

client = WebClient(
    token=SLACK_TOKEN,
    headers={"Cookie": f"d={SLACK_COOKIE}"},
)

# Cache mapping Slack user IDs to display names
_user_cache: dict[str, str] = {}


def _resolve_user(user_id: str) -> str:
    """Resolve a Slack user ID to a display name, with caching."""
    if not user_id or user_id == "unknown":
        return "unknown"
    if user_id in _user_cache:
        return _user_cache[user_id]
    try:
        resp = client.users_info(user=user_id)
        profile = resp["user"].get("profile", {})
        name = (
            profile.get("display_name")
            or profile.get("real_name")
            or resp["user"].get("real_name")
            or resp["user"].get("name")
            or user_id
        )
        _user_cache[user_id] = name
        return name
    except SlackApiError:
        _user_cache[user_id] = user_id
        return user_id


def _find_user_id(username: str) -> tuple[str, str] | None:
    """Find a Slack user ID by matching display name, real name, or username.

    Returns (user_id, display_name) or None if not found.

    If the input is already a Slack user ID (e.g. U0A3LPN2FKP), resolves it
    directly via users.info.  Otherwise, searches the workspace user list for a
    case-insensitive partial match on display/real name.
    """
    cleaned = username.strip().lstrip("@")

    # If input is already a user ID, resolve directly
    if re.fullmatch(r"U[A-Z0-9]+", cleaned):
        display = _resolve_user(cleaned)
        if display != cleaned:
            return cleaned, display
        return None

    query = cleaned.lower()

    # Fast path: search messages by the user to find their ID
    try:
        response = client.search_messages(query=f"from:{cleaned}", count=1)
        matches = response.get("messages", {}).get("matches", [])
        if matches and matches[0].get("user"):
            user_id = matches[0]["user"]
            return user_id, _resolve_user(user_id)
    except SlackApiError:
        pass

    # Fallback: scan workspace user list (slow on large workspaces)
    try:
        cursor = None
        while True:
            response = client.users_list(limit=200, cursor=cursor or "")
            for member in response.get("members", []):
                if member.get("deleted") or member.get("is_bot"):
                    continue
                profile = member.get("profile", {})
                display = (
                    profile.get("display_name")
                    or profile.get("real_name")
                    or member.get("real_name")
                    or member.get("name")
                    or ""
                )
                if display and query in display.lower():
                    _user_cache[member["id"]] = display
                    return member["id"], display
            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
    except SlackApiError:
        pass

    return None


def _open_dm(user_id: str) -> str | None:
    """Open (or get) a DM channel with a user. Returns channel ID or None."""
    try:
        resp = client.conversations_open(users=[user_id])
        return resp["channel"]["id"]
    except SlackApiError:
        return None


def _format_message(msg: dict) -> str:
    """Format a single Slack message for display."""
    user_id = msg.get("user", "unknown")
    user = _resolve_user(user_id)
    text = msg.get("text", "")
    ts = msg.get("ts", "")
    return f"[{ts}] {user}: {text}"


def _resolve_channel_id(name: str) -> tuple[str, str] | None:
    """Resolve a channel name to (channel_id, channel_name) via search.

    Returns None if the channel cannot be found.
    """
    cleaned = name.strip().lstrip("#")
    try:
        response = client.search_messages(query=f"in:#{cleaned}", count=1)
        matches = response.get("messages", {}).get("matches", [])
        if matches:
            channel = matches[0].get("channel", {})
            ch_id = channel.get("id", "")
            ch_name = channel.get("name", cleaned)
            if ch_id:
                return ch_id, ch_name
    except SlackApiError:
        pass
    return None


@mcp.tool()
async def find_channel(name: str) -> str:
    """Find a Slack channel ID by name.

    Use this when you need the raw channel ID (e.g. for register_slack_thread).
    For reading messages, use read_channel directly with the channel name.

    Args:
        name: Channel name (e.g. "team-quay-downstream-dev").
              The leading "#" is stripped automatically.
    """
    result = _resolve_channel_id(name)
    if result:
        return f"{result[0]}: #{result[1]}"
    return f"No channel found matching '{name}'."


@mcp.tool()
async def read_channel(channel: str, limit: int = 20) -> str:
    """Read recent messages from a Slack channel.

    Accepts a channel name (e.g. "team-quay-downstream-dev") or a channel ID
    (e.g. "C0123ABC"). Channel names are resolved automatically.

    Args:
        channel: Channel name or ID. Leading "#" is stripped automatically.
        limit: Number of messages to retrieve (max 100, default 20).
    """
    limit = min(max(1, limit), 100)
    cleaned = channel.strip().lstrip("#")

    # Resolve channel name to ID if needed
    if re.fullmatch(r"C[A-Z0-9]+", cleaned):
        channel_id = cleaned
    else:
        result = _resolve_channel_id(cleaned)
        if not result:
            return f"No channel found matching '{channel}'."
        channel_id = result[0]

    try:
        response = client.conversations_history(channel=channel_id, limit=limit)
        if not response["messages"]:
            return "No messages found in this channel."
        lines = [_format_message(m) for m in reversed(response["messages"])]
        return "\n".join(lines)
    except SlackApiError as e:
        return f"Slack API error: {e.response['error']}"


@mcp.tool()
async def read_dm(username: str, limit: int = 20) -> str:
    """Read recent messages from a direct message conversation with a user.

    Use this instead of search_messages for reading DM history, as Slack's
    search API may not index DMs on all workspaces.

    Args:
        username: Display name, real name, or Slack username of the person.
                  Case-insensitive partial match (e.g. "marcus" matches "Marcus Kok").
        limit: Number of messages to retrieve (max 100, default 20).
    """
    limit = min(max(1, limit), 100)
    result = _find_user_id(username)
    if result is None:
        return f"No Slack user found matching '{username}'."
    user_id, display_name = result
    channel_id = _open_dm(user_id)
    if channel_id is None:
        return f"Could not open DM channel with {display_name}."
    try:
        response = client.conversations_history(channel=channel_id, limit=limit)
        if not response["messages"]:
            return f"No messages in DM with {display_name}."
        lines = [_format_message(m) for m in reversed(response["messages"])]
        return f"DM with {display_name}:\n" + "\n".join(lines)
    except SlackApiError as e:
        return f"Slack API error: {e.response['error']}"


@mcp.tool()
async def search_messages(query: str, limit: int = 10) -> str:
    """Search Slack messages across all accessible channels.

    NOTE: DM search may not work on all workspaces due to Slack privacy
    settings. Use read_dm instead for reading DM conversations directly.

    Supports Slack search operators:
        from:@user     — messages sent by a specific user
        in:#channel    — messages in a specific channel
        has:link       — messages containing links
        on:2024-01-01  — messages on a specific date
        before:2024-01-01 — messages before a date (exclusive)
        after:2024-01-01  — messages after a date (exclusive, excludes that day)
        during:today/yesterday/week/month — relative date ranges

    Args:
        query: Slack search query string (supports operators above).
        limit: Number of results to return (max 50, default 10).
    """
    limit = min(max(1, limit), 50)
    try:
        response = client.search_messages(query=query, count=limit)
        matches = response.get("messages", {}).get("matches", [])
        if not matches:
            return f"No messages found matching '{query}'."
        lines = []
        for m in matches:
            channel_name = m.get("channel", {}).get("name", "unknown")
            # DM channels use the other user's ID as the channel name
            if re.fullmatch(r"U[A-Z0-9]+", channel_name):
                channel_label = f"@{_resolve_user(channel_name)} (DM)"
            else:
                channel_label = f"#{channel_name}"
            raw_user = m.get("user", m.get("username", "unknown"))
            user = _resolve_user(raw_user)
            text = m.get("text", "")
            ts = m.get("ts", "")
            lines.append(f"[{ts}] {channel_label} | {user}: {text}")
        return "\n".join(lines)
    except SlackApiError as e:
        return f"Slack API error: {e.response['error']}"


@mcp.tool()
async def send_note_to_self(message: str) -> str:
    """Send a private message to your own Slack DM.

    This is the only way to send messages — it is hardcoded to your own
    member ID so no messages can be sent to other users or channels.

    Args:
        message: The message text to send to yourself.
    """
    if not MY_MEMBER_ID:
        return "Error: MY_MEMBER_ID is not configured."
    try:
        dm = client.conversations_open(users=[MY_MEMBER_ID])
        channel_id = dm["channel"]["id"]
        prefixed = f"[rhclaw]: {message}"
        response = client.chat_postMessage(
            channel=channel_id,
            text=prefixed,
            unfurl_links=False,
            unfurl_media=False,
            metadata={"event_type": "rhclaw_note", "event_payload": {}},
        )
        return f"Sent to yourself! (Timestamp: {response['ts']})"
    except SlackApiError as e:
        return f"Slack API error: {e.response['error']}"


@mcp.tool()
async def read_my_notes(limit: int = 5) -> str:
    """Read the latest messages from your personal Slack DM history.

    Args:
        limit: Number of messages to retrieve (max 50, default 5).
    """
    if not MY_MEMBER_ID:
        return "Error: MY_MEMBER_ID is not configured."
    limit = min(max(1, limit), 50)
    try:
        dm = client.conversations_open(users=[MY_MEMBER_ID])
        channel_id = dm["channel"]["id"]
        response = client.conversations_history(channel=channel_id, limit=limit)
        if not response["messages"]:
            return "No messages in your personal DM."
        lines = [_format_message(m) for m in reversed(response["messages"])]
        return "\n".join(lines)
    except SlackApiError as e:
        return f"Slack API error: {e.response['error']}"


if __name__ == "__main__":
    mcp.run()
