"""
agents/ — J.A.R.V.I.S five-agent system
Shared context is stored here and imported by every agent module.
"""

from agents.router import AgentRouter  # noqa: F401 (re-export)

# Shared runtime context — populated by init() at startup
_ctx: dict = {
    "gemini":    None,   # callable(text) -> str
    "bridge":    None,   # ClaudeCodeBridge instance
    "reminders": [],     # list of {"time": str, "text": str}
    "alexa":     [],     # list of device dicts
}


def init(ask_gemini_fn, bridge, reminders, alexa_devices):
    """Called once from jarvis_backend.py after all objects are ready."""
    _ctx["gemini"]    = ask_gemini_fn
    _ctx["bridge"]    = bridge
    _ctx["reminders"] = reminders
    _ctx["alexa"]     = alexa_devices
