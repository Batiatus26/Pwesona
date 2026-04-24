from agents.base import BaseAgent


class AgentResearch(BaseAgent):
    name = "RESEARCH"
    icon = "⌕"
    _TRIGGERS = (
        "research ", "search for ", "search ", "find information",
        "look up ", "look up", "google ", "what is ", "what are ",
        "who is ", "who was ", "when did ", "where is ", "where was ",
        "tell me about ", "explain ", "how does ", "how do ",
        "why does ", "why is ", "summarize ", "give me info",
    )

    def handle(self, text: str) -> str:
        query = self._strip_trigger(text)

        web_snippet = self._web_search(query)
        if web_snippet:
            return self._gemini(
                f"Using this web search result as context, give a concise 2-3 sentence "
                f"answer as JARVIS would, addressing the user as Sir: "
                f"Query: {query} | Web result: {web_snippet}"
            )

        return self._gemini(
            f"Research and provide a concise, accurate 2-4 sentence summary as JARVIS, "
            f"addressing the user as Sir: {query}"
        )

    @staticmethod
    def _web_search(query: str) -> str:
        """DuckDuckGo Instant Answer API — no API key required."""
        try:
            import requests
            r = requests.get(
                "https://api.duckduckgo.com/",
                params={
                    "q":           query,
                    "format":      "json",
                    "no_html":     "1",
                    "no_redirect": "1",
                    "skip_disambig": "1",
                },
                headers={"User-Agent": "JARVIS/4.0"},
                timeout=5,
            )
            data = r.json()

            # Best case: Wikipedia-style abstract
            if data.get("AbstractText"):
                return data["AbstractText"][:600]

            # Fallback: related topics snippets
            topics = data.get("RelatedTopics", [])
            snippets = [
                t["Text"] for t in topics
                if isinstance(t, dict) and "Text" in t
            ]
            if snippets:
                return " | ".join(snippets[:3])[:600]

        except Exception:
            pass
        return ""
