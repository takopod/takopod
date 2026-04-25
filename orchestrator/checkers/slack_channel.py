"""Slack channel checker — passive observer for new messages."""

from __future__ import annotations

import asyncio
import logging

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from orchestrator.checkers import CheckResult, register

logger = logging.getLogger(__name__)

MAX_MESSAGES = 50


def _build_slack_client() -> WebClient | None:
    from orchestrator.slack_routes import _read_slack_config

    config = _read_slack_config()
    if not config:
        return None
    return WebClient(
        token=config["xoxc_token"],
        headers={"Cookie": f"d={config['d_cookie']}"},
    )


@register("slack_channel", requires_mcp="slack")
async def check_slack_channel(config: dict, cursor: dict) -> CheckResult:
    channel_id = config.get("channel_id", "")
    if not channel_id:
        return CheckResult(changed=False, new_cursor=cursor, summary="")

    client = _build_slack_client()
    if client is None:
        logger.warning("Slack not configured, skipping slack_channel checker")
        return CheckResult(changed=False, new_cursor=cursor, summary="")

    last_ts = cursor.get("last_ts", "0")

    try:
        response = await asyncio.to_thread(
            client.conversations_history,
            channel=channel_id,
            oldest=last_ts,
            limit=MAX_MESSAGES,
        )
    except SlackApiError as e:
        logger.warning("Slack API error polling channel %s: %s", channel_id, e)
        return CheckResult(changed=False, new_cursor=cursor, summary="")

    messages = response.get("messages", [])
    if not messages:
        return CheckResult(changed=False, new_cursor=cursor, summary="")

    # Filter out bot messages and non-content subtypes
    filtered = []
    highest_ts = last_ts
    for msg in messages:
        ts = msg.get("ts", "")
        if ts <= last_ts:
            continue
        if ts > highest_ts:
            highest_ts = ts
        if msg.get("bot_id"):
            continue
        subtype = msg.get("subtype")
        if subtype and subtype != "file_share":
            continue
        text = msg.get("text", "")
        if not text:
            continue
        if text.startswith("[bot:"):
            continue
        filtered.append(msg)

    if not filtered:
        new_cursor = {"last_ts": highest_ts}
        return CheckResult(changed=False, new_cursor=new_cursor, summary="")

    # Build summary: format messages oldest-first
    channel_name = config.get("channel_name", channel_id)
    lines: list[str] = []
    for msg in reversed(filtered):
        user = msg.get("user", "unknown")
        text = msg.get("text", "")[:500]
        lines.append(f"{user}: {text}")

    new_cursor = {"last_ts": highest_ts}
    has_more = response.get("has_more", False)
    truncation = ""
    if has_more:
        truncation = f"\n\n[Showing {len(filtered)} of more messages — some were truncated]"

    summary = (
        f"New messages in #{channel_name} ({len(filtered)} message(s)):\n\n"
        + "\n".join(lines)
        + truncation
    )
    return CheckResult(changed=True, new_cursor=new_cursor, summary=summary)
