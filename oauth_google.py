# oauth_google.py
from __future__ import annotations
import os
import secrets
from typing import Dict, Any

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from google_auth_oauthlib.flow import Flow

router = APIRouter()

_sessions: Dict[str, Dict[str, Any]] = {}

def init(sessions: Dict[str, Dict[str, Any]]):
    global _sessions
    _sessions = sessions

def _get_sid(req: Request) -> str:
    sid = req.cookies.get("sid")
    if not sid:
        import uuid
        sid = str(uuid.uuid4())
    return sid

def _build_flow(state: str) -> Flow:
    """
    Uses OAuth *web application* client.
    """
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")  # e.g. https://xxxx.gradio.live/auth/callback

    if not client_id or not client_secret or not redirect_uri:
        raise RuntimeError("Missing GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REDIRECT_URI in .env")

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        },
        scopes=["https://www.googleapis.com/auth/calendar.events"],
        state=state,
    )
    flow.redirect_uri = redirect_uri
    return flow

@router.get("/auth/google")
def auth_google(request: Request):
    sid = _get_sid(request)

    csrf = secrets.token_urlsafe(24)
    _sessions.setdefault(sid, {})
    _sessions[sid]["oauth_csrf"] = csrf

    flow = _build_flow(state=csrf)
    auth_url, _ = flow.authorization_url(
        access_type="offline",           # to receive refresh_token
        include_granted_scopes="true",
        prompt="consent",                # force refresh_token the first time
    )

    resp = RedirectResponse(auth_url)
    resp.set_cookie("sid", sid, httponly=True, samesite="lax")
    return resp

@router.get("/google/callback")
def auth_callback(request: Request, state: str, code: str):
    sid = _get_sid(request)
    saved = _sessions.get(sid, {}).get("oauth_csrf")
    if not saved or saved != state:
        return HTMLResponse("OAuth state mismatch. Please retry /auth/google", status_code=400)

    flow = _build_flow(state=state)
    flow.fetch_token(code=code)

    creds = flow.credentials
    _sessions.setdefault(sid, {})
    _sessions[sid]["google_tokens"] = {
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,   # may be None if Google didn't return it
    }

    # simple success page
    html = """
    <html><body style="font-family:system-ui;padding:24px;">
      <h2>✅ Google Calendar connected</h2>
      <p>You can now return to <a href="/chat">Chat</a> or <a href="/voice">Voice</a> and confirm the booking.</p>
    </body></html>
    """
    resp = HTMLResponse(html)
    resp.set_cookie("sid", sid, httponly=True, samesite="lax")
    return resp