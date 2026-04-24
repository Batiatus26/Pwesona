from agents.base import BaseAgent
from agents import _ctx


class AgentSmartHome(BaseAgent):
    name = "SMART HOME"
    icon = "⌂"
    _TRIGGERS = (
        "turn on ", "turn off ", "switch on", "switch off",
        "set the lights", "dim the lights", "lights on", "lights off",
        "thermostat", "set temperature", "heat", "heating",
        "alexa ", "volume", "mute", "unmute",
        "tv on", "tv off", "television",
        "bedroom light", "living room", "kitchen light",
    )

    # Map trigger keywords to device name fragments
    _DEVICE_MAP = {
        "living room": "LIVING ROOM",
        "bedroom":     "BEDROOM",
        "thermostat":  "THERMOSTAT",
        "heat":        "THERMOSTAT",
        "tv":          "TV",
        "television":  "TV",
        "speaker":     "SPEAKER",
        "volume":      "SPEAKER",
        "mute":        "SPEAKER",
    }

    def handle(self, text: str) -> str:
        lower   = text.lower()
        turning_on  = "on"  in lower and "off" not in lower
        turning_off = "off" in lower

        # Find which device(s) to target
        targets = []
        for keyword, dev_name in self._DEVICE_MAP.items():
            if keyword in lower:
                targets.append(dev_name)

        # If "lights" is mentioned without a room, target all lights
        if "lights" in lower and not targets:
            targets = ["LIVING ROOM", "BEDROOM"]

        # Mutate the shared alexa list so the HUD reflects the change
        changed = []
        for device in _ctx["alexa"]:
            if any(t in device["name"] for t in targets):
                if turning_off:
                    device["state"] = "OFF"
                    device["val"]   = "--"
                    changed.append(device["name"])
                elif turning_on:
                    device["state"] = "ON"
                    device["val"]   = "AUTO"
                    changed.append(device["name"])

        if changed:
            action = "activated" if turning_on else "deactivated"
            names  = " and ".join(changed)
            return f"Very good, Sir. I have {action} {names}."

        # No direct match — ask Gemini with full device context
        states = ", ".join(
            f"{d['name']} ({d['type']}) is {d['state']} at {d['val']}"
            for d in _ctx["alexa"]
        )
        return self._gemini(
            f"You are JARVIS managing smart home devices via Alexa. "
            f"Current states: {states}. "
            f"Handle this request and describe exactly what you do: {text}"
        )
