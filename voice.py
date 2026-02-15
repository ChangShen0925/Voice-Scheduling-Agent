# voice.py
from __future__ import annotations

import os
import io
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from dotenv import load_dotenv
from fastapi import APIRouter, Request, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from openai import OpenAI
from calendar_event import create_google_calendar_event

load_dotenv(override=True)

router = APIRouter()

_templates: Optional[Jinja2Templates] = None
_sessions: Dict[str, Dict[str, Any]] = {}

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-4.1-nano")
ASR_MODEL = os.getenv("ASR_MODEL", "gpt-4o-mini-transcribe")

TZ_NAME = os.getenv("TZ_NAME", "America/Los_Angeles")
CALENDAR_ID = os.getenv("CALENDAR_ID", "primary")
DEFAULT_DURATION_MIN = int(os.getenv("MEETING_DURATION_MIN", "30"))
DEFAULT_TITLE = os.getenv("DEFAULT_TITLE", "Scheduled Meeting")

TTS_MODEL = os.getenv("TTS_MODEL", "gpt-4o-mini-tts")
TTS_VOICE = os.getenv("TTS_VOICE", "alloy")


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


def _get_history(sid: str) -> List[dict]:
    sess = _sessions.setdefault(sid, {})
    print(sess)
    if "voice_history" not in sess:
        sess["voice_history"] = []
    return sess["voice_history"]


SYSTEM_PROMPT = """
You are a friendly real-time voice scheduling assistant.

Goal:
Book a meeting by collecting:
- name
- email
- phone
- preferred date & time
- optional title

Rules:
- Ask ONLY ONE question each turn.
- Be casual, short, natural.
- Do NOT repeat questions if the user already provided the info.
- Once you have everything, repeat the full details and ask: "Is this correct? (yes/no)"
- If user says yes, DO NOT talk anymore. Just reply with: CONFIRMED
"""


DECIDE_PROMPT = """
You are a strict decision maker.

Given the full conversation, decide if the user has confirmed the meeting details.

Return ONLY JSON:
{
  "status": "collecting" | "confirmed",
  "reason": string
}

Rules:
- status=confirmed only if user clearly confirmed yes/correct/that's right.
- Otherwise collecting.
"""


FINALIZE_PROMPT = """
You are an assistant that prepares Google Calendar event data.

Given the full conversation, extract the final meeting details.

Return ONLY JSON:
{{
  "title": string,
  "start_iso": string,
  "duration_min": integer,
  "attendee_email": string,
  "description": string
}}

You must include "title", "start_iso", "duration_min", "attendee_email" and "description"

Rules:
- start_iso must be ISO8601 with timezone offset, example:
  2026-02-16T14:00:00-08:00
- Timezone: {tz_name}
- duration_min default: {duration_min}
- title default: "{default_title}"
- attendee_email MUST be a valid email.
- description should include name + phone.
- Do NOT hallucinate. If missing, still make best reasonable guess.
"""



def _llm_finalize_event(history: List[dict]) -> dict:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "title": {"type": "string"},
            "start_iso": {"type": "string"},
            "duration_min": {"type": "integer"},
            "attendee_email": {"type": "string"},
            "description": {"type": "string"},
        },
        "required": ["title", "start_iso", "duration_min", "attendee_email", "description"],
    }
    r = client.responses.create(
        model=CHAT_MODEL,
        input=[
            {"role": "system", "content": FINALIZE_PROMPT.format(
                tz_name=TZ_NAME,
                duration_min=DEFAULT_DURATION_MIN,
                default_title=DEFAULT_TITLE,
            )},
            *history,
        ],
        text={"format": {"type": "json_schema", "name": "finalize", "schema": schema}},
    )
    return json.loads(r.output_text)


def _stream_assistant(history: List[dict]):
    with client.responses.stream(
        model=CHAT_MODEL,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            *history,
        ],
    ) as stream:
        for event in stream:
            if event.type == "response.output_text.delta":
                if event.delta:
                    yield event.delta


@router.get("/voice", response_class=HTMLResponse)
def voice_page(request: Request):
    assert _templates is not None
    return _templates.TemplateResponse("voice.html", {"request": request})


@router.post("/api/asr")
async def api_asr(audio: UploadFile = File(...)):
    data = await audio.read()
    f = io.BytesIO(data)
    f.name = audio.filename or "audio.webm"

    r = client.audio.transcriptions.create(
        model=ASR_MODEL,
        file=f,
    )
    return {"text": (r.text or "").strip()}


@router.post("/api/voice/chat/stream")
async def voice_chat_stream(request: Request):
    payload = await request.json()

    if "messages" in payload and payload["messages"]:
        user_text = (payload["messages"][-1].get("content") or "").strip()
    else:
        user_text = (payload.get("text") or "").strip()

    if not user_text:
        def one():
            msg = "I didn’t catch that. Can you say it again?"
            yield f"data: {json.dumps({'type': 'delta', 'text': msg})}\n\n"
            yield f"data: {json.dumps({'type': 'final_text', 'text': msg})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        return StreamingResponse(one(), media_type="text/event-stream")
    sid = _get_sid(request)
    history = _get_history(sid)

    # save user message
    history.append({"role": "user", "content": user_text})
    history[:] = history[-20:]
    tokens = _get_tokens(sid)
    if not tokens:
        def one():
            msg = "⚠️ Google Calendar is not connected. Please open /auth/google first."
            yield f"data: {json.dumps({'type':'delta','text':msg})}\n\n"
            yield f"data: {json.dumps({'type':'final_text','text':msg})}\n\n"
            yield f"data: {json.dumps({'type':'done'})}\n\n"
        resp = StreamingResponse(one(), media_type="text/event-stream")
        resp.set_cookie("sid", sid, httponly=True, samesite="lax")
        return resp
    def sse():
        assistant_text = ""

        # stream assistant normal reply
        for chunk in _stream_assistant(history):
            assistant_text += chunk
            yield f"data: {json.dumps({'type':'delta','text':chunk})}\n\n"

        # store assistant reply
        history.append({"role": "assistant", "content": assistant_text})
        history[:] = history[-20:]

        # if assistant said CONFIRMED -> create event
        if "CONFIRMED" in assistant_text:
            fixed = "One second — I'm creating the meeting details for you now."
            yield f"data: {json.dumps({'type':'delta','text':fixed})}\n\n"

            try:
                event_data = _llm_finalize_event(history)
                start_dt = datetime.fromisoformat(event_data["start_iso"])
                end_dt = start_dt + timedelta(minutes=int(event_data["duration_min"]))

                created = create_google_calendar_event(
                    access_token=tokens["access_token"],
                    calendar_id=CALENDAR_ID,
                    title=event_data["title"],
                    start_dt=start_dt,
                    end_dt=end_dt,
                    tz_name=TZ_NAME,
                    attendee_email=event_data["attendee_email"],
                    description=event_data["description"],
                )

                meet_link = created.get("hangoutLink")
                html_link = created.get("htmlLink")

                extra = "\n\n✅ Done! Your meeting is booked."
                if meet_link:
                    extra += f"\nMeet link: {meet_link}"
                if html_link:
                    extra += f"\nCalendar link: {html_link}"
                extra += f"\nInvite sent to: {event_data['attendee_email']}"

                yield f"data: {json.dumps({'type':'delta','text':extra})}\n\n"

                # reset history after booking
                _sessions[sid]["voice_history"] = []

            except Exception as e:
                err = f"\n\n⚠️ Failed to create calendar event: {e}"
                yield f"data: {json.dumps({'type':'delta','text':err})}\n\n"

        yield f"data: {json.dumps({'type':'final_text','text': assistant_text})}\n\n"
        yield f"data: {json.dumps({'type':'done'})}\n\n"

    resp = StreamingResponse(sse(), media_type="text/event-stream")
    resp.set_cookie("sid", sid, httponly=True, samesite="lax")
    return resp


@router.post("/api/tts/stream")
async def tts_stream(request: Request):
    payload = await request.json()
    text = (payload.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "missing text"}, status_code=400)

    def audio_iter():
        with client.audio.speech.with_streaming_response.create(
            model=TTS_MODEL,
            voice=TTS_VOICE,
            input=text,
            response_format="mp3",
        ) as resp:
            for chunk in resp.iter_bytes(chunk_size=8192):
                if chunk:
                    yield chunk

    return StreamingResponse(audio_iter(), media_type="audio/mpeg")