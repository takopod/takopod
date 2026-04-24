"""Claude Agent SDK integration.

Translates SDK messages into events (token, tool_call, tool_result, complete)
persisted via the worker's emit() callback for the orchestrator to consume.
"""

import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Callable

from worker.context_budget import (
    ContextConfig,
    SectionBudget,
    assemble_system_prompt,
    get_config,
    log_usage_report,
)

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    HookMatcher,
    ResultMessage,
    SystemMessage,
    TextBlock,
    query,
)

from worker.tools import (
    TOOL_NAMES as BUILTIN_TOOL_NAMES,
    create_mcp_proxy_servers,
    create_memory_server,
    create_schedule_server,
    create_slack_thread_server,
)

WORKSPACE = Path("/workspace")
MAX_TURNS = 25


DEFAULT_BUILTIN_TOOLS = [
    "Read", "Write", "Edit", "Bash",
    "Glob", "Grep", "WebSearch", "WebFetch",
]


def _load_tool_config() -> tuple[list[str], str]:
    """Load per-agent tool configuration from /workspace/tools.json."""
    config_path = WORKSPACE / "tools.json"
    if config_path.is_file():
        try:
            config = json.loads(config_path.read_text())
            builtin = config.get("builtin", DEFAULT_BUILTIN_TOOLS)
            permission_mode = config.get("permission_mode", "acceptEdits")
            return builtin, permission_mode
        except (json.JSONDecodeError, KeyError):
            pass
    return list(DEFAULT_BUILTIN_TOOLS), "acceptEdits"

Emit = Callable[[dict[str, Any]], None]


def _build_system_prompt(
    retrieved_context: str | None = None,
    memory_context: str | None = None,
    continuation_summary: str | None = None,
    facts_context: str | None = None,
    config: ContextConfig | None = None,
) -> str:
    """Assemble system prompt from identity files, memory, and retrieved context.

    Uses the token budget system to allocate space to each section and
    truncate/omit lower-priority sections when the budget is exhausted.

    Priority order (1 = highest):
      1. Identity (CLAUDE.md + SOUL.md)
      2. Continuation summary
      3. Active plan (task plan from .plans/)
      4. Facts (structured key-value pairs from memory)
      5. MEMORY.md (persistent user-curated context)
      6. Agents list
      7. Search results
    """
    if config is None:
        config = get_config()

    # --- Gather raw content for each section ---

    identity_parts: list[str] = []
    claude_md = WORKSPACE / "CLAUDE.md"
    if claude_md.is_file():
        identity_parts.append(claude_md.read_text().strip())
    soul_md = WORKSPACE / "SOUL.md"
    if soul_md.is_file():
        identity_parts.append(soul_md.read_text().strip())
    identity_content = "\n\n".join(identity_parts)

    agents_content = ""
    agents_json = WORKSPACE / "agents.json"
    if agents_json.is_file():
        try:
            agents = json.loads(agents_json.read_text())
            if agents:
                agent_list = "\n".join(f"- {a['name']}" for a in agents)
                agents_content = (
                    "## Available Delegation Targets\n\n"
                    "The following agents are available for delegation:\n"
                    + agent_list
                )
        except (json.JSONDecodeError, KeyError):
            pass

    # Load active plan content
    plan_content = ""
    plans_dir = WORKSPACE / ".plans"
    if plans_dir.is_dir():
        active_plans = [f for f in sorted(plans_dir.glob("*.md")) if f.is_file()]
        if active_plans:
            plan_file = active_plans[0]
            plan_text = plan_file.read_text().strip()
            plan_content = (
                "## Active Plan\n\n"
                "You have an active task plan. Resume from the first unchecked item.\n"
                f"Plan file: /workspace/.plans/{plan_file.name}\n\n"
                f"{plan_text}"
            )

    search_content = ""
    if retrieved_context:
        search_content = (
            "## Relevant Past Conversations\n\n"
            "The following excerpts are from previous conversations "
            "and may be relevant:\n\n"
            + retrieved_context
        )

    continuation_content = ""
    if continuation_summary:
        continuation_content = (
            "## Continuation Context\n\n"
            "The conversation was automatically split due to context length. "
            "Below is a summary of the prior conversation:\n\n"
            + continuation_summary
        )

    # --- Build section budget list ---

    sections = [
        SectionBudget(
            name="identity",
            max_tokens=config.identity_tokens,
            priority=1,
            content=identity_content,
        ),
        SectionBudget(
            name="continuation",
            max_tokens=config.continuation_tokens,
            priority=2,
            content=continuation_content,
        ),
        SectionBudget(
            name="active_plan",
            max_tokens=config.plan_tokens,
            priority=3,
            content=plan_content,
        ),
        SectionBudget(
            name="facts",
            max_tokens=config.facts_tokens,
            priority=4,
            content=facts_context or "",
        ),
        SectionBudget(
            name="memory_md",
            max_tokens=config.memory_md_tokens,
            priority=5,
            content=memory_context or "",
        ),
        SectionBudget(
            name="agents_list",
            max_tokens=config.agents_list_tokens,
            priority=6,
            content=agents_content,
        ),
        SectionBudget(
            name="search",
            max_tokens=config.search_tokens,
            priority=7,
            content=search_content,
        ),
    ]

    prompt, usage_report = assemble_system_prompt(sections, config.total_max_tokens)
    log_usage_report(usage_report)

    return prompt


def _should_self_assess(
    usage: dict[str, int],
    response_text: str,
    tool_call_count: int,
    original_message: str,
    msg_payload: dict,
) -> bool:
    """Determine if self-assessment should run based on response complexity."""
    # Disabled by default -- check for opt-in
    config_path = WORKSPACE / "context_config.json"
    if config_path.is_file():
        try:
            config = json.loads(config_path.read_text())
            if not config.get("self_assessment_enabled", False):
                return False
        except (json.JSONDecodeError, KeyError):
            return False
    else:
        return False  # No config file = disabled

    # Skip for delegated messages
    source = msg_payload.get("source", "user")
    if source == "delegation":
        return False

    # Skip for scheduled tasks
    if source == "scheduled_task":
        return False

    # Threshold checks
    if tool_call_count > 5:
        return True
    if len(response_text) > 2000:
        return True
    return False


async def _run_self_assessment(
    user_message: str,
    agent_response: str,
) -> str:
    """Run a lightweight self-check on the response.

    Uses a single SDK call with no tools, short system prompt, max_turns=1.
    Returns the assessment note or empty string on failure.
    """
    user_excerpt = user_message[:1000]
    response_excerpt = agent_response[:3000]

    assessment_prompt = (
        "You are a quality reviewer. The user sent a message and the assistant responded. "
        "Evaluate: does the response address what the user asked for?\n\n"
        f"USER MESSAGE:\n{user_excerpt}\n\n"
        f"ASSISTANT RESPONSE:\n{response_excerpt}\n\n"
        "If the response fully addresses the request, reply with exactly:\n"
        "[Self-check: Response addresses the request. No issues detected.]\n\n"
        "If there is a mismatch or something was missed, reply with:\n"
        "[Self-check: <brief description of what was missed or mismatched>]\n\n"
        "Reply with ONLY the self-check line, nothing else."
    )

    try:
        opts = ClaudeAgentOptions(
            cwd=str(WORKSPACE),
            allowed_tools=[],
            system_prompt="You are a concise quality reviewer.",
            max_turns=1,
            permission_mode="acceptEdits",
        )

        result_text = ""
        async with asyncio.timeout(10):
            async for msg in query(prompt=assessment_prompt, options=opts):
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            result_text += block.text

        if result_text.strip().startswith("[Self-check:"):
            return result_text.strip()
        return ""

    except Exception as e:
        sys.stderr.write(f"agent: self-assessment failed: {e}\n")
        sys.stderr.flush()
        return ""


async def run_query(
    message_id: str,
    content: str,
    session_id: str | None,
    emit: Emit,
    conn: sqlite3.Connection | None = None,
    retrieved_context: str | None = None,
    memory_context: str | None = None,
    continuation_summary: str | None = None,
    facts_context: str | None = None,
    msg_payload: dict[str, Any] | None = None,
    partial_text_ref: list[str] | None = None,
) -> tuple[str | None, dict[str, Any], str]:
    """Run a query through the Claude Agent SDK.

    Returns (captured_session_id, usage_dict, full_response_text).
    """
    system_prompt = _build_system_prompt(
        retrieved_context, memory_context, continuation_summary,
        facts_context=facts_context,
    )
    sys.stderr.write(
        f"agent: system_prompt ({len(system_prompt)} chars):\n{system_prompt}\n"
    )
    sys.stderr.flush()

    # Emit tool events via hooks so the frontend can display them
    tool_call_count = 0

    async def on_pre_tool(input_data, tool_use_id, context):
        nonlocal tool_call_count
        tool_call_count += 1
        tool_name = input_data.get("tool_name", "unknown")
        sys.stderr.write(
            f"agent: tool_call {tool_name} id={tool_use_id}\n"
            f"{json.dumps(input_data, indent=2)}\n"
        )
        sys.stderr.flush()
        emit({
            "type": "tool_call",
            "tool_name": tool_name,
            "tool_input": input_data.get("tool_input", {}),
            "tool_call_id": tool_use_id,
            "message_id": message_id,
        })
        return {}

    async def on_post_tool(input_data, tool_use_id, context):
        output = input_data.get("output", "")
        if isinstance(output, dict):
            output = json.dumps(output)
        output_str = str(output)

        tool_name = input_data.get("tool_name", "unknown")
        sys.stderr.write(
            f"agent: tool_result {tool_name} id={tool_use_id}\n"
            f"{output_str}\n"
        )
        sys.stderr.flush()
        if tool_name in ("Write", "Edit", "Bash"):
            os.sync()
        emit({
            "type": "tool_result",
            "tool_call_id": tool_use_id,
            "output": output_str[:4000],
            "message_id": message_id,
        })
        return {}

    schedule_server = create_schedule_server()
    slack_thread_server = create_slack_thread_server()
    mcp_proxy_servers = create_mcp_proxy_servers()
    builtin_tools, permission_mode = _load_tool_config()

    memory_server = None
    if conn is not None:
        memory_server = create_memory_server(conn)

    mcp_servers: dict[str, Any] = {
        "schedule": schedule_server,
        "slack_thread": slack_thread_server,
    }
    if memory_server is not None:
        mcp_servers["memory"] = memory_server
    mcp_proxy_tool_names: list[str] = []
    for server_name, proxy_server, proxy_tool_names in mcp_proxy_servers:
        mcp_servers[server_name] = proxy_server
        mcp_proxy_tool_names.extend(proxy_tool_names)

    # Check if skills exist to enable the Skill tool
    skills_dir = WORKSPACE / ".claude" / "skills"
    has_skills = skills_dir.is_dir() and any(p.is_dir() for p in skills_dir.iterdir())

    allowed = [*builtin_tools, *BUILTIN_TOOL_NAMES, *mcp_proxy_tool_names]
    if has_skills:
        allowed.append("Skill")

    opts_kwargs: dict[str, Any] = {
        "cwd": str(WORKSPACE),
        "allowed_tools": allowed,
        "setting_sources": ["project"],
        "permission_mode": permission_mode,
        "system_prompt": system_prompt,
        "max_turns": MAX_TURNS,
        "mcp_servers": mcp_servers,
        "hooks": {
            "PreToolUse": [HookMatcher(matcher=".*", hooks=[on_pre_tool])],
            "PostToolUse": [HookMatcher(matcher=".*", hooks=[on_post_tool])],
        },
    }
    if session_id:
        opts_kwargs["resume"] = session_id

    options = ClaudeAgentOptions(**opts_kwargs)

    # Log the full query() call for debugging
    log_kwargs = {k: v for k, v in opts_kwargs.items() if k not in ("hooks", "mcp_servers")}
    log_kwargs["prompt"] = content
    sys.stderr.write(f"agent: query() call:\n{json.dumps(log_kwargs, indent=2)}\n")
    sys.stderr.flush()

    captured_session_id = session_id
    total_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
    full_text_parts: list[str] = []
    seq = 0
    last_emitted_text = ""

    emit({"type": "status", "status": "generating", "message_id": message_id})

    async for msg in query(prompt=content, options=options):
        if isinstance(msg, SystemMessage) and msg.subtype == "init":
            captured_session_id = msg.data.get("session_id")
            sys.stderr.write(
                f"agent: SDK session_id={captured_session_id}\n"
            )
            sys.stderr.flush()

        elif isinstance(msg, AssistantMessage):
            if msg.usage:
                total_usage["input_tokens"] += msg.usage.get("input_tokens", 0)
                total_usage["output_tokens"] += msg.usage.get("output_tokens", 0)

            for block in msg.content:
                if isinstance(block, TextBlock):
                    seq += 1
                    full_text_parts.append(block.text)
                    emit({
                        "type": "token",
                        "content": block.text,
                        "message_id": message_id,
                        "seq": seq,
                    })
            current_text = "\n\n".join(full_text_parts)
            if partial_text_ref is not None:
                partial_text_ref[0] = current_text
            if current_text != last_emitted_text:
                emit({
                    "type": "assistant_message",
                    "content": current_text,
                    "message_id": message_id,
                    "seq": seq,
                })
                last_emitted_text = current_text
                sys.stderr.write(
                    f"agent: AssistantMessage seq={seq}\n"
                    f"{current_text[:200]}\n"
                )
                sys.stderr.flush()

        elif isinstance(msg, ResultMessage):
            sys.stderr.write("agent: ResultMessage (query complete)\n")
            sys.stderr.flush()

    full_text = "\n\n".join(full_text_parts)

    # Self-assessment: run a lightweight quality check on qualifying responses
    assessment_note = ""
    if _should_self_assess(
        total_usage, full_text, tool_call_count, content,
        msg_payload or {},
    ):
        assessment_note = await _run_self_assessment(content, full_text)

    if assessment_note:
        full_text = full_text + "\n\n" + assessment_note
        seq += 1
        emit({
            "type": "token",
            "content": "\n\n" + assessment_note,
            "message_id": message_id,
            "seq": seq,
        })

    sys.stderr.write(
        f"agent: emitting complete, {len(full_text_parts)} text blocks, "
        f"{total_usage.get('input_tokens', 0)}+{total_usage.get('output_tokens', 0)} tokens\n"
    )
    sys.stderr.flush()
    emit({
        "type": "complete",
        "content": full_text,
        "message_id": message_id,
        "usage": total_usage,
    })
    # Drain: ensure all pending events (including the complete above)
    # are flushed to output.json before returning.
    from worker.worker import drain_pending
    drain_pending()

    return captured_session_id, total_usage, full_text
