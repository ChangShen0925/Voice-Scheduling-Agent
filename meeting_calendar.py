# meeting_calendar.py
from __future__ import annotations
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import uuid

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

def create_google_meet_event(
    creds: Credentials,
    calendar_id: str,
    summary: str,
    start_dt: datetime,
    duration_min: int,
    attendee_email: Optional[str] = None,
) -> Dict[str, Any]:
    service = build("calendar", "v3", credentials=creds)

    end_dt = start_dt + timedelta(minutes=duration_min)

    event_body: Dict[str, Any] = {
        "summary": summary,
        "start": {"dateTime": start_dt.isoformat()},
        "end": {"dateTime": end_dt.isoformat()},
        "conferenceData": {
            "createRequest": {
                "requestId": str(uuid.uuid4()),
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
    }
    if attendee_email:
        event_body["attendees"] = [{"email": attendee_email}]

    created = (
        service.events()
        .insert(calendarId=calendar_id, body=event_body, conferenceDataVersion=1)
        .execute()
    )
    return created