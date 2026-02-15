# chat.py
from __future__ import annotations

import os
import json
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from dotenv import load_dotenv
from openai import OpenAI

from calendar_event import create_google_calendar_event

load_dotenv(override=True)

router = APIRouter()
_templates: Optional[Jinja2Templates] = None
_sessions: Dict[str, Dict[str, Any]] = {}

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
TZ_NAME = os.getenv("TZ_NAME", "America/Los_Angeles")
CALENDAR_ID = os.getenv("CALENDAR_ID", "primary")
DEFAULT_DURATION_MIN = int(os.getenv("MEETING_DURATION_MIN", "30"))
DEFAULT_TITLE = os.getenv("DEFAULT_TITLE", "Scheduled Meeting")
CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-4.1-nano")


def init(*, templates: Jinja2Templates, sessions: Dict[str, Dict[str, Any]]):
    global _templates, _sessions
    _templates = templates
    _sessions = sessions


def _get_sid(req: Request) -> str:
    sid = req.cookies.get("sid")
    if not sid:
        import uuid
        sid = str(uuid.uuid4())
    return sid


def _get_tokens(sid: str) -> Optional[Dict[str, str]]:
    return _sessions.get(sid, {}).get("google_tokens")


@dataclass
class BookingState:
    step: str = "ask_email_phone"  # ask_email_phone -> confirm_contact -> ask_time -> ask_title -> confirm_all -> done
    email: Optional[str] = None
    phone: Optional[str] = None
    start_iso: Optional[str] = None
    title: Optional[str] = None


def _load_state(sid: str) -> BookingState:
    raw = _sessions.setdefault(sid, {}).get("booking_state")
    if not raw:
        st = BookingState()
        _sessions[sid]["booking_state"] = asdict(st)
        return st
    return BookingState(**raw)


def _save_state(sid: str, st: BookingState):
    _sessions.setdefault(sid, {})["booking_state"] = asdict(st)


def _is_yes(text: str) -> bool:
    t = (text or "").strip().lower()
    return t in {"yes", "y", "yeah", "yep", "confirm", "ok", "okay", "sure"}


def _is_no(text: str) -> bool:
    t = (text or "").strip().lower()
    return t in {"no", "n", "nope", "cancel", "restart"}


def _parse_iso_datetime(s: str) -> Optional[datetime]:
    """
    Parse ISO-8601 string produced by LLM.
    Accepts trailing 'Z' by converting to +00:00.
    """
    if not s:
        return None
    try:
        s2 = s.strip()
        if s2.endswith("Z"):
            s2 = s2[:-1] + "+00:00"
        return datetime.fromisoformat(s2)
    except Exception:
        return None


# -------------------------
# LLM planner (extract + validate + normalize)
# -------------------------
PLANNER_SYSTEM = f"""
You are a strict planner for a scheduling agent.
Return ONLY JSON (no markdown, no extra text).

Your job:
1) Extract email, phone, meeting datetime, and optional title from the user's message.
2) Validate whether each extracted field is valid.
3) Normalize:
   - email: lowercased, trimmed
   - phone: try best to E.164 (e.g. +14155552671). If impossible, return null.
   - start_iso: MUST be ISO 8601 with timezone offset (e.g. 2026-02-16T14:00:00-08:00).
     Use timezone name: {TZ_NAME}. If user did not specify a timezone, interpret in {TZ_NAME}.
4) Detect confirmation intent: yes/no if user is confirming or rejecting.

Do NOT hallucinate. If not provided, output null.
If user input is ambiguous for time (e.g., missing date), mark start_ok=false.

Return JSON:
{{
  "extracted": {{
    "email": string|null,
    "email_ok": boolean,
    "phone": string|null,
    "phone_ok": boolean,
    "start_iso": string|null,
    "start_ok": boolean,
    "title": string|null,
    "confirm": "yes"|"no"|null
  }},
  "notes": {{
    "email_reason": string|null,
    "phone_reason": string|null,
    "time_reason": string|null
  }}
}}
"""


def llm_extract_and_validate(user_text: str, state: BookingState) -> Dict[str, Any]:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "extracted": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "email": {"type": ["string", "null"]},
                    "email_ok": {"type": "boolean"},
                    "phone": {"type": ["string", "null"]},
                    "phone_ok": {"type": "boolean"},
                    "start_iso": {"type": ["string", "null"]},
                    "start_ok": {"type": "boolean"},
                    "title": {"type": ["string", "null"]},
                    "confirm": {"type": ["string", "null"], "enum": ["yes", "no", None]},
                },
                "required": ["email", "email_ok", "phone", "phone_ok", "start_iso", "start_ok", "title", "confirm"],
            },
            "notes": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "email_reason": {"type": ["string", "null"]},
                    "phone_reason": {"type": ["string", "null"]},
                    "time_reason": {"type": ["string", "null"]},
                },
                "required": ["email_reason", "phone_reason", "time_reason"],
            },
        },
        "required": ["extracted", "notes"],
    }

    r = client.responses.create(
        model=CHAT_MODEL,
        input=[
            {"role": "system", "content": PLANNER_SYSTEM},
            {"role": "user", "content": f"STATE={json.dumps(asdict(state))}\nUSER={user_text}"},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "planner",
                "schema": schema,
                "strict": True,
            }
        },
    )
    try:
        return json.loads(r.output_text)
    except Exception:
        # safe fallback
        return {
            "extracted": {
                "email": None, "email_ok": False,
                "phone": None, "phone_ok": False,
                "start_iso": None, "start_ok": False,
                "title": None,
                "confirm": None
            },
            "notes": {"email_reason": "parse_error", "phone_reason": "parse_error", "time_reason": "parse_error"}
        }


# -------------------------
# LLM speaker (stream)
# -------------------------
def llm_stream_reply(user_text: str, state: BookingState, planned_assistant_text: str):
    system = f"""
You are a scheduling assistant.
Be concise and helpful.

Current step: {state.step}
Known info:
- email: {state.email}
- phone: {state.phone}
- start_iso: {state.start_iso}
- title: {state.title}

You must follow the planned assistant message exactly in meaning.
Do NOT mention internal JSON or planning.
"""

    with client.responses.stream(
        model=CHAT_MODEL,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"User said: {user_text}\n\nPlanned assistant message:\n{planned_assistant_text}"},
        ],
    ) as stream:
        for event in stream:
            if event.type == "response.output_text.delta":
                chunk = event.delta or ""
                if chunk:
                    yield chunk


def _contact_summary(st: BookingState) -> str:
    return f"Email: {st.email or '(missing)'}\nPhone: {st.phone or '(missing)'}"


def _final_summary(st: BookingState) -> str:
    return (
        f"Email: {st.email}\n"
        f"Phone: {st.phone}\n"
        f"Start: {st.start_iso} ({TZ_NAME})\n"
        f"Title: {st.title or DEFAULT_TITLE}\n"
    )


@router.get("/chat", response_class=HTMLResponse)
def chat_page(request: Request):
    assert _templates is not None
    return _templates.TemplateResponse("chat.html", {"request": request})


@router.post("/api/chat/stream")
async def chat_stream(request: Request):
    payload = await request.json()
    messages = payload.get("messages") or []
    user_text = (messages[-1]["content"] if messages else "").strip()

    sid = _get_sid(request)
    st = _load_state(sid)

    tokens = _get_tokens(sid)
    if not tokens:
        def one():
            msg = "⚠️ Google Calendar is not connected yet. Please complete OAuth login first: /auth/google"
            yield f"data: {json.dumps({'type':'delta','text':msg})}\n\n"
            yield f"data: {json.dumps({'type':'done'})}\n\n"
        return StreamingResponse(one(), media_type="text/event-stream")

    # LLM extract+validate
    plan = llm_extract_and_validate(user_text, st)
    ex = plan.get("extracted") or {}
    notes = plan.get("notes") or {}

    confirm = ex.get("confirm")
    # explicit user yes/no wins
    if _is_yes(user_text):
        confirm = "yes"
    elif _is_no(user_text):
        confirm = "no"

    planned_text = ""

    # -------------------------
    # step machine (no nlu, trust planner fields)
    # -------------------------
    if st.step == "ask_email_phone":
        if ex.get("email_ok") and ex.get("email"):
            st.email = ex["email"].strip().lower()
        if ex.get("phone_ok") and ex.get("phone"):
            st.phone = ex["phone"].strip()[:40]

        if not st.email or not st.phone:
            reason_email = notes.get("email_reason") or ""
            reason_phone = notes.get("phone_reason") or ""
            planned_text = (
                "Please provide BOTH a valid email and a valid phone number in one message.\n"
                "Example: john@example.com, +1 415 555 2671\n"
            )
            if reason_email or reason_phone:
                planned_text += f"\n(Details: email={reason_email or 'missing'}, phone={reason_phone or 'missing'})"
        else:
            st.step = "confirm_contact"
            planned_text = "Thanks! Please confirm these details:\n" + _contact_summary(st) + "\n\nReply 'yes' to confirm or 'no' to re-enter."

    elif st.step == "confirm_contact":
        if confirm == "no":
            st = BookingState(step="ask_email_phone")
            planned_text = "No problem. Please tell me your email and phone number again."
        elif confirm == "yes":
            st.step = "ask_time"
            planned_text = "Great. What date and time would you like to schedule the meeting?"
        else:
            planned_text = "Please reply 'yes' to confirm or 'no' to re-enter your email and phone."

    elif st.step == "ask_time":
        if ex.get("start_ok") and ex.get("start_iso"):
            dt = _parse_iso_datetime(ex["start_iso"])
            if dt is None:
                planned_text = "Sorry — I couldn’t parse that time. Please try again (e.g., 'Feb 16 2pm')."
            else:
                st.start_iso = ex["start_iso"]
                st.step = "ask_title"
                planned_text = "Optional: what’s the meeting title? You can say 'skip'."
        else:
            reason = notes.get("time_reason") or "missing/ambiguous"
            planned_text = (
                "Sorry, I couldn’t understand the date/time.\n"
                "Try: 'Feb 16 2pm' or 'next Monday 3pm'.\n"
                f"(Details: {reason})"
            )

    elif st.step == "ask_title":
        # title is optional; accept "skip"
        t = (ex.get("title") or user_text).strip()
        if t.lower() in {"skip", "no", "none"}:
            st.title = DEFAULT_TITLE
        else:
            st.title = t[:120] if t else DEFAULT_TITLE

        st.step = "confirm_all"
        planned_text = "Please confirm the meeting details:\n" + _final_summary(st) + "\nCreate the calendar event now? (yes/no)"

    elif st.step == "confirm_all":
        if confirm == "no":
            st.step = "ask_time"
            st.start_iso = None
            planned_text = "Okay. Let’s pick a new time. What date and time would you like?"
        elif confirm == "yes":
            planned_text = "Got it — creating your calendar event now…"
        else:
            planned_text = "Please reply 'yes' to create the event or 'no' to change the time."

    elif st.step == "done":
        planned_text = "Your event is already created. Click Clear to start a new booking."

    _save_state(sid, st)

    # -------------------------
    # SSE stream
    # -------------------------
    def sse():
        # A) stream the assistant reply
        for chunk in llm_stream_reply(user_text, st, planned_text):
            yield f"data: {json.dumps({'type':'delta','text':chunk})}\n\n"

        # B) after streaming, if user confirmed in confirm_all -> create event
        st2 = _load_state(sid)
        if st2.step == "confirm_all" and (confirm == "yes") and st2.start_iso and st2.email and st2.phone:
            try:
                start_dt = _parse_iso_datetime(st2.start_iso)
                if start_dt is None:
                    yield f"data: {json.dumps({'type':'delta','text':'\\n\\n⚠️ Internal error: invalid start_iso format.'})}\n\n"
                else:
                    end_dt = start_dt + timedelta(minutes=DEFAULT_DURATION_MIN)

                    created = create_google_calendar_event(
                        access_token=tokens["access_token"],
                        calendar_id=CALENDAR_ID,
                        title=st2.title or DEFAULT_TITLE,
                        start_dt=start_dt,
                        end_dt=end_dt,
                        tz_name=TZ_NAME,
                        attendee_email=st2.email,  # invite email will be sent by Google Calendar
                        description=f"Phone: {st2.phone}",
                    )

                    html_link = created.get("htmlLink")
                    meet_link = created.get("hangoutLink")

                    st2.step = "done"
                    _save_state(sid, st2)

                    extra = "\n\n✅ Event created!\n"
                    if meet_link:
                        extra += f"Meet link: {meet_link}\n"
                    if html_link:
                        extra += f"Calendar link: {html_link}\n"
                    extra += f"Invite email sent to: {st2.email}"

                    yield f"data: {json.dumps({'type':'delta','text':extra})}\n\n"

            except Exception as e:
                yield f"data: {json.dumps({'type':'delta','text':f'\\n\\n⚠️ Failed to create event: {e}'})}\n\n"

        yield f"data: {json.dumps({'type':'done'})}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream")