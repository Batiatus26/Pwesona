from agents.base import BaseAgent
from agents import _ctx


class AgentCoding(BaseAgent):
    name = "CODING"
    icon = "</>"
    _TRIGGERS = (
        "code ", "claude code ", "send to claude ", "hey claude ",
        "write a function", "write a script", "write a class",
        "fix the bug", "fix the error", "fix this",
        "implement ", "refactor ", "debug ", "create a class",
        "add a feature", "make a program",
    )

    def handle(self, text: str) -> str:
        prompt = self._strip_trigger(text)
        bridge = _ctx["bridge"]

        if bridge is None or not bridge.status == "ONLINE":
            # No SSH bridge — answer with Gemini
            return self._gemini(
                f"You are an expert software engineer. Provide a clear, concise "
                f"coding answer (code first, then one-line explanation): {prompt}"
            )

        ok, result = bridge.run(prompt)
        if ok:
            # Return first non-empty line — the voice-readable summary
            for line in result.splitlines():
                line = line.strip()
                if line and not line.startswith("```"):
                    return line[:300]
            return result[:300]

        # Bridge failed — Gemini fallback
        return (
            f"SSH bridge error, Sir. {result[:80]}. "
            f"Falling back to local Gemini. "
            + self._gemini(prompt)
        )
