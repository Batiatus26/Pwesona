"""
Shared runtime context for all agents.
Imported by every agent module — never imports from agents/ itself.
"""

_ctx: dict = {
    "gemini":    None,   # callable(text) -> str
    "bridge":    None,   # ClaudeCodeBridge instance
    "reminders": [],     # list of {"time": str, "text": str}
    "alexa":     [],     # list of device dicts
}
