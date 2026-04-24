from agents import _ctx


class BaseAgent:
    name     = "BASE"
    icon     = "◈"
    _TRIGGERS: tuple = ()

    def can_handle(self, text: str) -> bool:
        lower = text.lower()
        return any(t in lower for t in self._TRIGGERS)

    def handle(self, text: str) -> str:
        raise NotImplementedError

    def _gemini(self, prompt: str) -> str:
        return _ctx["gemini"](prompt)

    def _strip_trigger(self, text: str) -> str:
        """Remove leading trigger phrase from the user's text."""
        lower = text.lower()
        for t in self._TRIGGERS:
            if lower.startswith(t):
                return text[len(t):].strip()
        return text
