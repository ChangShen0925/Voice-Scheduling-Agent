# agent_state.py
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any
import re

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^\+?[0-9][0-9\s\-()]{6,}$")

def normalize_phone(s: str) -> str:
    s = (s or "").strip()
    return re.sub(r"[^\d+]", "", s)

def is_valid_email(s: str) -> bool:
    return bool(EMAIL_RE.match((s or "").strip().lower()))

def is_valid_phone(s: str) -> bool:
    return bool(PHONE_RE.match(normalize_phone(s)))

def parse_yes_no(text: str) -> Optional[bool]:
    t = (text or "").strip().lower()
    if t in {"yes", "y", "yeah", "yep", "confirm", "correct", "ok", "okay"}:
        return True
    if t in {"no", "n", "nope", "cancel", "restart"}:
        return False
    return None

@dataclass
class BookingState:
    step: str = "ask_email"     # ask_email -> ask_phone -> confirm -> done
    email: Optional[str] = None
    phone: Optional[str] = None
    title: str = "Scheduled Meeting"

def build_confirmation(st: BookingState) -> str:
    return (
        "Please confirm the details:\n"
        f"- Email: {st.email}\n"
        f"- Phone: {st.phone}\n\n"
        "Reply with **yes** to confirm, or **no** to restart."
    )

def handle_user_message(state: BookingState, user_text: str) -> Dict[str, Any]:
    user_text = (user_text or "").strip()

    if state.step == "ask_email":
        if not is_valid_email(user_text):
            return {"state": state, "reply": "Please provide a valid email address (e.g., john.doe@gmail.com).", "action": None}
        state.email = user_text.strip().lower()
        state.step = "ask_phone"
        return {"state": state, "reply": "Thanks! Now please provide your phone number (digits, may include +).", "action": None}

    if state.step == "ask_phone":
        if not is_valid_phone(user_text):
            return {"state": state, "reply": "Please provide a valid phone number (e.g., +14155552671).", "action": None}
        state.phone = normalize_phone(user_text)
        state.step = "confirm"
        return {"state": state, "reply": build_confirmation(state), "action": None}

    if state.step == "confirm":
        yn = parse_yes_no(user_text)
        if yn is None:
            return {"state": state, "reply": "Please reply with **yes** to confirm or **no** to restart.", "action": None}
        if yn is False:
            return {"state": BookingState(step="ask_email", title=state.title), "reply": "No problem — let’s start over.\nWhat’s your email?", "action": None}

        state.step = "done"
        return {"state": state, "reply": "Great — creating your meeting now…", "action": {"type": "create_meeting"}}

    if state.step == "done":
        return {"state": state, "reply": "This session is already completed. Clear to start a new one.", "action": None}

    return {"state": state, "reply": "I’m not sure what to do next.", "action": None}

def state_to_dict(st: BookingState) -> Dict[str, Any]:
    return asdict(st)

def dict_to_state(d: Dict[str, Any]) -> BookingState:
    return BookingState(**(d or {}))