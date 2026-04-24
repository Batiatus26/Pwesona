import datetime
import re
from agents.base import BaseAgent
from agents.context import _ctx


class AgentCalendar(BaseAgent):
    name = "CALENDAR"
    icon = "▦"
    _TRIGGERS = (
        "remind me", "set a reminder", "add a reminder",
        "schedule ", "appointment", "meeting ",
        "calendar", "agenda", "what's on",
        "what time is", "tomorrow", "next week",
        "add event", "cancel reminder", "delete reminder",
        "what are my reminders", "show reminders",
    )

    def handle(self, text: str) -> str:
        lower = text.lower()

        # Show all reminders
        if any(k in lower for k in ("show reminder", "what are my reminder", "list reminder", "agenda")):
            return self._list_reminders()

        # Add a new reminder
        if any(k in lower for k in ("remind me", "set a reminder", "add a reminder", "add event")):
            return self._add_reminder(text)

        # Cancel / delete
        if any(k in lower for k in ("cancel", "delete", "remove")):
            return self._remove_reminder(text)

        # General calendar query → Gemini with context
        now     = datetime.datetime.now()
        rem_str = self._reminders_str()
        return self._gemini(
            f"Current date/time: {now.strftime('%A, %B %d %Y, %H:%M')}. "
            f"Scheduled reminders: {rem_str}. "
            f"Handle this calendar request as JARVIS, addressing the user as Sir: {text}"
        )

    # ── helpers ──────────────────────────────────────────────────

    def _list_reminders(self) -> str:
        reminders = _ctx["reminders"]
        if not reminders:
            return "You have no reminders scheduled, Sir."
        items = ", ".join(f"{r['time']}: {r['text']}" for r in reminders)
        return f"Your scheduled reminders, Sir: {items}."

    def _add_reminder(self, text: str) -> str:
        # Try to extract HH:MM time from text
        match = re.search(r'\b(\d{1,2})[:\.](\d{2})\b', text)
        if match:
            hh, mm = match.group(1).zfill(2), match.group(2)
            time_str = f"{hh}:{mm}"
            # Strip time and trigger words to get the reminder label
            label = re.sub(r'\b\d{1,2}[:.]\d{2}\b', '', text)
            for kw in ("remind me", "at", "to", "set a reminder", "add a reminder"):
                label = label.replace(kw, "")
            label = " ".join(label.split()) or "Reminder"
            _ctx["reminders"].append({"time": time_str, "text": label.title()})
            _ctx["reminders"].sort(key=lambda r: r["time"])
            return f"Reminder set for {time_str}: {label.title()}. Confirmed, Sir."

        # No time found — ask Gemini to interpret and confirm
        now = datetime.datetime.now()
        return self._gemini(
            f"Current time: {now.strftime('%H:%M')}. "
            f"The user said: '{text}'. "
            f"Acknowledge the reminder request as JARVIS (Sir), and ask for a specific time if none was given."
        )

    def _remove_reminder(self, text: str) -> str:
        lower = text.lower()
        before = len(_ctx["reminders"])
        _ctx["reminders"] = [
            r for r in _ctx["reminders"]
            if r["text"].lower() not in lower
        ]
        removed = before - len(_ctx["reminders"])
        if removed:
            return f"Removed {removed} reminder{'s' if removed > 1 else ''}, Sir."
        return "No matching reminder found, Sir. Please check your wording."

    def _reminders_str(self) -> str:
        if not _ctx["reminders"]:
            return "none"
        return ", ".join(f"{r['time']}: {r['text']}" for r in _ctx["reminders"])
