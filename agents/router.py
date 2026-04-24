from agents import _ctx
from agents.coding    import AgentCoding
from agents.smarthome import AgentSmartHome
from agents.research  import AgentResearch
from agents.social    import AgentSocialMedia
from agents.calendar  import AgentCalendar


class AgentRouter:
    """
    Routes a user utterance to the most appropriate agent.
    Priority: Coding > SmartHome > Calendar > Research > Social > JARVIS (Gemini)
    """

    def __init__(self):
        self._agents = [
            AgentCoding(),
            AgentSmartHome(),
            AgentCalendar(),
            AgentResearch(),
            AgentSocialMedia(),
        ]

    def route(self, text: str) -> tuple[str, str, str]:
        """
        Returns (agent_name, response, agent_icon).
        Falls back to bare Gemini if no agent claims the text.
        """
        for agent in self._agents:
            try:
                if agent.can_handle(text):
                    return agent.name, agent.handle(text), agent.icon
            except Exception as e:
                return agent.name, f"Agent error, Sir: {e}", agent.icon

        # Default: JARVIS speaks directly via Gemini
        return "JARVIS", _ctx["gemini"](text), "◈"

    @property
    def agents(self) -> list:
        return self._agents
