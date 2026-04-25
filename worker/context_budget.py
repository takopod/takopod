"""Token budget management for system prompt assembly.

Allocates a fixed token budget to each context section, truncates sections
that exceed their allocation, and omits sections when no budget remains.
Token estimation uses len(text) // 4 (chars divided by 4).
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    """Estimate token count from character length."""
    return len(text) // 4


@dataclass(frozen=True)
class ContextConfig:
    """Budget allocations for system prompt sections.

    All values are in estimated tokens (chars // 4).
    Frozen dataclass -- defaults are not configurable per-agent.
    """

    total_max_tokens: int = 15000
    identity_tokens: int = 4000       # CLAUDE.md + SOUL.md combined
    facts_tokens: int = 1000          # structured facts from memory files
    memory_md_tokens: int = 2000      # MEMORY.md persistent memory
    search_tokens: int = 3000         # hybrid search results
    continuation_tokens: int = 2000   # continuation summary after split
    plan_tokens: int = 1500           # active task plan from .plans/
    retention_days: int = 90          # P3: prune index entries older than this


# Singleton -- no per-agent overrides.
_CONFIG = ContextConfig()


def get_config() -> ContextConfig:
    """Return the global ContextConfig instance."""
    return _CONFIG


@dataclass
class SectionBudget:
    """Budget allocation for a single system prompt section."""

    name: str
    max_tokens: int
    priority: int       # lower = higher priority, filled first
    content: str = ""
    actual_tokens: int = 0
    truncated: bool = False


def truncate_text(text: str, max_tokens: int) -> tuple[str, bool]:
    """Truncate text to fit within max_tokens using tail strategy.

    Keeps the first max_tokens * 4 characters, breaking at a newline
    boundary when possible, and appends a truncation marker.
    Returns (truncated_text, was_truncated).
    """
    actual = estimate_tokens(text)
    if actual <= max_tokens:
        return text, False

    max_chars = max_tokens * 4
    # Find the nearest newline boundary before max_chars
    cut = text.rfind("\n", 0, max_chars)
    if cut < max_chars // 2:
        # No good newline boundary in the second half -- just cut at max_chars
        cut = max_chars
    truncated = text[:cut].rstrip() + "\n\n[...truncated]"
    return truncated, True


def assemble_system_prompt(
    sections: list[SectionBudget],
    total_max: int,
) -> tuple[str, dict[str, dict]]:
    """Fill sections in priority order within a total token budget.

    Returns (assembled_prompt, usage_report). The usage_report maps
    section name to {"budget": int, "actual": int, "truncated": bool}.
    """
    sorted_sections = sorted(sections, key=lambda s: s.priority)
    remaining = total_max
    usage_report: dict[str, dict] = {}

    for section in sorted_sections:
        if not section.content:
            usage_report[section.name] = {
                "budget": section.max_tokens,
                "actual": 0,
                "truncated": False,
            }
            continue

        actual = estimate_tokens(section.content)
        effective_limit = min(section.max_tokens, remaining)

        if effective_limit <= 0:
            # No budget left -- omit entirely
            section.content = ""
            section.actual_tokens = 0
            section.truncated = True
            usage_report[section.name] = {
                "budget": section.max_tokens,
                "actual": 0,
                "truncated": True,
            }
            continue

        if actual <= effective_limit:
            # Fits within budget
            section.actual_tokens = actual
            section.truncated = False
        else:
            # Truncate to fit
            section.content, _ = truncate_text(section.content, effective_limit)
            section.actual_tokens = estimate_tokens(section.content)
            section.truncated = True

        remaining -= section.actual_tokens
        usage_report[section.name] = {
            "budget": section.max_tokens,
            "actual": section.actual_tokens,
            "truncated": section.truncated,
        }

    # Join non-empty sections in priority order
    assembled = "\n\n".join(
        s.content for s in sorted_sections if s.content
    )

    return assembled, usage_report


def log_usage_report(usage_report: dict[str, dict]) -> None:
    """Log token budget usage for each section."""
    for name, info in usage_report.items():
        truncated_marker = " TRUNCATED" if info["truncated"] else ""
        logger.debug(
            "Budget [%s] %d/%d tokens%s",
            name, info["actual"], info["budget"], truncated_marker,
        )
