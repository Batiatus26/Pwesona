"""
J.A.R.V.I.S — Five-Agent System
Each agent has can_handle() + handle(). AgentRouter picks the right one.
"""

import datetime


# ── shared references injected at startup ────────────────────
_ask_gemini  = None   # callable
_bridge      = None   # ClaudeCodeBridge instance
_reminders   = []
_alexa       = []


def init(ask_gemini_fn, bridge, reminders, alexa_devices):
    global _ask_gemini, _bridge, _reminders, _alexa
    _ask_gemini = ask_gemini_fn
    _bridge     = bridge
    _reminders  = reminders
    _alexa      = alexa_devices


# ══════════════════════════════════════════════════════════════
class BaseAgent:
    name = "BASE"

    def can_handle(self, text: str) -> bool:
        raise NotImplementedError

    def handle(self, text: str) -> str:
        raise NotImplementedError

    def _gemini(self, prompt: str) -> str:
        return _ask_gemini(prompt)


# ══════════════════════════════════════════════════════════════
class CodingAgent(BaseAgent):
    name = "CODING"
    _TRIGGERS = (
        "code ", "claude code ", "send to claude ", "hey claude ",
        "write a function", "write a script", "fix the bug", "fix the error",
        "implement ", "refactor ", "debug ", "create a class",
    )

    def can_handle(self, text: str) -> bool:
        lower = text.lower()
        return any(t in lower for t in self._TRIGGERS)

    def handle(self, text: str) -> str:
        # strip any leading trigger word
        for t in self._TRIGGERS:
            if text.lower().startswith(t):
                text = text[len(t):].strip()
                break
        if _bridge is None:
            return self._gemini(f"Provide a coding answer for: {text}")
        ok, result = _bridge.run(text)
        if ok:
            first = result.split("\n")[0][:200]
            return first if first else result[:200]
        return f"Bridge error, Sir. Falling back to Gemini. {self._gemini(text)}"


# ══════════════════════════════════════════════════════════════
class SocialAgent(BaseAgent):
    name = "SOCIAL"
    _TRIGGERS = (
        "tweet ", "post on twitter", "post to twitter", "linkedin post",
        "instagram post", "share on social", "draft a post",
        "write a tweet", "social media",
    )

    def can_handle(self, text: str) -> bool:
        lower = text.lower()
        return any(t in lower for t in self._TRIGGERS)

    def handle(self, text: str) -> str:
        return self._gemini(
            f"You are a social media expert. Draft a professional, engaging post "
            f"(max 280 chars for Twitter) for: {text}. "
            f"Return only the post text, no explanation."
        )


# ══════════════════════════════════════════════════════════════
class ResearchAgent(BaseAgent):
    name = "RESEARCH"
    _TRIGGERS = (
        "research ", "search for ", "find information", "look up ",
        "what is ", "who is ", "when did ", "where is ",
        "tell me about ", "explain ", "how does ", "why does ",
        "summarize ",
    )

    def can_handle(self, text: str) -> bool:
        lower = text.lower()
        return any(t in lower for t in self._TRIGGERS)

    def handle(self, text: str) -> str:
        return self._gemini(
            f"Research and provide a concise, accurate summary (3–5 sentences) of: {text}"
        )


# ══════════════════════════════════════════════════════════════
class SmartHomeAgent(BaseAgent):
    name = "SMART HOME"
    _TRIGGERS = (
        "turn on ", "turn off ", "switch on", "switch off",
        "lights", "thermostat", "temperature", "heating",
        "alexa ", "speaker", "volume", "tv ", "television",
        "bedroom", "living room", "kitchen",
    )

    def can_handle(self, text: str) -> bool:
        lower = text.lower()
        return any(t in lower for t in self._TRIGGERS)

    def handle(self, text: str) -> str:
        # Build device context for Gemini
        states = ", ".join(
            f"{d['name']} ({d['type']}) is {d['state']} at {d['val']}"
            for d in _alexa
        )
        return self._gemini(
            f"You are JARVIS managing smart home devices. "
            f"Current device states: {states}. "
            f"Respond to this request and describe what you would do: {text}"
        )


# ══════════════════════════════════════════════════════════════
class CalendarAgent(BaseAgent):
    name = "CALENDAR"
    _TRIGGERS = (
        "remind me", "set a reminder", "schedule ", "appointment",
        "meeting ", "calendar", "agenda", "what's today",
        "what time is", "tomorrow", "next week", "add event",
    )

    def can_handle(self, text: str) -> bool:
        lower = text.lower()
        return any(t in lower for t in self._TRIGGERS)

    def handle(self, text: str) -> str:
        now     = datetime.datetime.now()
        rem_str = ", ".join(
            f"{r['time']}: {r['text']}" for r in _reminders
        )
        return self._gemini(
            f"Current date/time: {now.strftime('%A, %B %d %Y, %H:%M')}. "
            f"Scheduled reminders: {rem_str}. "
            f"Handle this calendar/reminder request as JARVIS: {text}"
        )


# ══════════════════════════════════════════════════════════════
#  ROUTER
# ══════════════════════════════════════════════════════════════
class AgentRouter:
    def __init__(self):
        self._agents = [
            CodingAgent(),
            SmartHomeAgent(),
            CalendarAgent(),
            ResearchAgent(),
            SocialAgent(),
        ]

    def route(self, text: str) -> tuple:
        """Returns (agent_name: str, response: str)."""
        for agent in self._agents:
            try:
                if agent.can_handle(text):
                    return agent.name, agent.handle(text)
            except Exception as e:
                return agent.name, f"Agent error: {e}"
        return "JARVIS", _ask_gemini(text)
