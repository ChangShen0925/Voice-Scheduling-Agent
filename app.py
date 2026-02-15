# app.py
import os
from typing import Dict, Any
from dotenv import load_dotenv

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

import chat
import voice
import oauth_google

load_dotenv(override=True)


app = FastAPI(title="Voice Scheduling Agent")

templates = Jinja2Templates(directory="templates")

# demo: in-memory sessions (use Redis in prod)
SESSIONS: Dict[str, Dict[str, Any]] = {}

chat.init(templates=templates, sessions=SESSIONS)
voice.init(templates=templates, sessions=SESSIONS)
oauth_google.init(sessions=SESSIONS)

app.include_router(oauth_google.router)
app.include_router(chat.router)
app.include_router(voice.router)

@app.get("/")
def home():
    return {
        "ok": True,
        "routes": {
            "chat_page": "/chat",
            "voice_page": "/voice",
            "oauth_start": "/auth/google",
            "oauth_callback": "/auth/callback",
        },
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "7860")),
        reload=os.getenv("RELOAD", "0") == "1",
    )