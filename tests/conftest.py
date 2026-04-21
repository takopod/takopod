"""Shared fixtures and SDK stubs for worker tests.

The claude_agent_sdk is only available inside the Podman worker container.
We stub it here so that worker modules can be imported in the test environment.
"""

import sys
import types

# Create a comprehensive stub for claude_agent_sdk before any worker imports
_sdk = types.ModuleType("claude_agent_sdk")

# Classes needed by worker.memory and worker.agent
for _name in [
    "ClaudeAgentOptions",
    "ClaudeAgent",
    "HookMatcher",
    "AssistantMessage",
    "ResultMessage",
    "TextBlock",
    "ToolResultContent",
]:
    setattr(_sdk, _name, type(_name, (), {}))

# Functions
_sdk.create_sdk_mcp_server = lambda **kw: None
_sdk.tool = lambda *args: (lambda fn: fn)
_sdk.query = lambda *args, **kwargs: None
_sdk.run_agent = lambda *args, **kwargs: None

sys.modules["claude_agent_sdk"] = _sdk
