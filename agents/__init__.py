"""
agents/ — J.A.R.V.I.S five-agent system
Shared context is stored here and imported by every agent module.
"""

from agents.context import _ctx          # noqa: F401 (re-export for convenience)
from agents.router import AgentRouter    # noqa: F401 (re-export)


def init(ask_gemini_fn, bridge, reminders, alexa_devices):
    """Called once from jarvis_backend.py after all objects are ready."""
    _ctx["gemini"]    = ask_gemini_fn
    _ctx["bridge"]    = bridge
    _ctx["reminders"] = reminders
    _ctx["alexa"]     = alexa_devices
