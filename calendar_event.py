# calendar_event.py
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime
from typing import Optional, Dict, Any

import httpx


GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_CAL_API = "https://www.googleapis.com/calendar/v3"


class GoogleAuthError(RuntimeError):
    pass


def refresh_access_token(*, refresh_token: str) -> Dict[str, Any]:
    """
    Refresh OAuth access token using refresh_token.
    Requires GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in env.
    """
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise GoogleAuthError("Missing GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET in env for token refresh")

    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }

    with httpx.Client(timeout=20) as client:
        r = client.post(GOOGLE_TOKEN_URL, data=data)
        if r.status_code != 200:
            raise GoogleAuthError(f"Failed to refresh token: {r.status_code} {r.text}")

        js = r.json()
        # js contains: access_token, expires_in, scope, token_type
        return js


def create_google_calendar_event(
    *,
    access_token: str,
    calendar_id: str,
    title: str,
    start_dt: datetime,
    end_dt: datetime,
    tz_name: str,
    attendee_email: str,
    description: str = "",
    location: str = "",
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a Google Calendar event with Google Meet link (conferenceData).
    Add attendee_email -> Google will send invite email automatically.
    """

    if not request_id:
        request_id = uuid.uuid4().hex

    def _do_create(token: str) -> httpx.Response:
        url = f"{GOOGLE_CAL_API}/calendars/{calendar_id}/events"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        body = {
            "summary": title,
            "description": description,
            "location": location,
            "start": {"dateTime": start_dt.isoformat(), "timeZone": tz_name},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": tz_name},
            "attendees": [{"email": attendee_email}],
            # Important: conferenceData requires conferenceDataVersion=1 in query
            "conferenceData": {
                "createRequest": {
                    "requestId": request_id,
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            },
        }

        with httpx.Client(timeout=25) as client:
            return client.post(
                url,
                headers=headers,
                params={"conferenceDataVersion": 1, "sendUpdates": "all"},
                json=body,
            )

    resp = _do_create(access_token)


    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Create event failed: {resp.status_code} {resp.text}")

    return resp.json()