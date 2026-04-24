from agents.base import BaseAgent


class AgentSocialMedia(BaseAgent):
    name = "SOCIAL"
    icon = "◉"
    _TRIGGERS = (
        "tweet ", "post on twitter", "post to twitter",
        "linkedin post", "linkedin ", "instagram post",
        "share on social", "draft a post", "write a post",
        "write a tweet", "social media post", "caption for",
    )

    _PLATFORM_HINTS = {
        "twitter":   ("Twitter/X",   280,  "concise, punchy, uses 1-2 hashtags"),
        "linkedin":  ("LinkedIn",     700,  "professional, insightful, no hashtag spam"),
        "instagram": ("Instagram",    300,  "visual, emoji-friendly, 3-5 hashtags"),
    }

    def handle(self, text: str) -> str:
        lower = text.lower()

        platform_key = "twitter"  # default
        for key in self._PLATFORM_HINTS:
            if key in lower:
                platform_key = key
                break

        name, max_chars, style = self._PLATFORM_HINTS[platform_key]

        return self._gemini(
            f"You are a professional social media strategist. "
            f"Draft a {name} post ({style}, max {max_chars} chars). "
            f"Topic: {text}. "
            f"Return ONLY the post text with no preamble, no quotes, no explanation."
        )
