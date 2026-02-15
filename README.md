# Voice Scheduling Agent (Real-Time, Deployed)

A real-time **Voice Scheduling Agent** that converses with the user, collects meeting details, confirms them, and creates a real Google Calendar event with a Meet link.

This project is designed as a production-style prototype for a take-home assignment:  
**Voice Scheduling Agent (Deployed)**.

---

## 🚀 Deployed Demo

This project is deployed on **Zeabur**.

---

## ✅ What This Agent Can Do

The agent supports the full required workflow:

### 1. Initiates a conversation
It greets the user and starts the scheduling flow automatically.

### 2. Collects required meeting information
It asks for:
- **Name**
- **Preferred date & time**
- **Email**
- **Phone number**
- *(Optional)* Meeting title

### 3. Confirms final details
The agent repeats all extracted information and asks for explicit confirmation ("yes/no").

### 4. Creates a real calendar event
Once confirmed, it creates an event via:
- **Google Calendar API**
- Auto-generates a **Google Meet link**

### 5. Fully voice-enabled
- **ASR (Speech → Text)** via OpenAI Audio Transcription
- **LLM conversation + reasoning** via OpenAI GPT model
- **Streaming response** via SSE
- **TTS (Text → Speech)** via OpenAI TTS streaming
- Clean and modern voice UI with "Hold to Talk" interaction

---

## 🧠 Architecture Overview

This project is built with a clean modular architecture:

### Backend (FastAPI)
- `app.py` – main entrypoint, mounts all routers
- `voice.py` – handles voice conversation flow + streaming response + streaming TTS
- `chat.py` – optional text-only chat page (same agent logic)
- `oauth_google.py` – handles Google OAuth login flow
- `calendar_event.py` – event creation logic (Google Calendar API)

### Frontend (Jinja + HTML + Vanilla JS)
- `templates/voice.html`
- Modern chat-like UI
- Voice input via `MediaRecorder`
- SSE streaming display
- Streaming TTS playback via `MediaSource`

---

## 🔊 Real-Time Streaming Design

This agent is built around a real-time streaming experience.

### Streaming Response (SSE)
Backend endpoint:
- `POST /api/voice/chat/stream`

Frontend consumes SSE stream and renders assistant output token-by-token.

### Streaming TTS (Audio chunks)
Backend endpoint:
- `POST /api/tts/stream`

Frontend plays MP3 audio progressively while it downloads.

---

## 🔑 Google Calendar Integration (OAuth2)

This project uses **Google OAuth2 Web Application Flow**.

### OAuth endpoints
- `/auth/google`  
  Starts OAuth login
- `/google/callback`  
  Receives the callback and stores tokens in cookie-based session

### Permissions used
- `https://www.googleapis.com/auth/calendar.events`

This allows the app to create events in the user's calendar.

---

## 📅 Calendar Event Creation Logic

Once the user confirms all details, the system performs:

1. The LLM extracts structured event fields from the full conversation history:
   - title
   - start datetime (ISO format)
   - duration
   - attendee email
   - description (includes name + phone)

2. Backend creates the event via Google Calendar API.

3. Google returns:
   - `hangoutLink` (Google Meet URL)
   - `htmlLink` (Calendar event link)

4. Agent returns these links to the user.

---

## 🧪 How to Test the Agent

### Step 1 — Open the voice UI
Go to:

```
/voice
```

Example:

```
http://127.0.0.1:7860/voice
```

---

### Step 2 — Login with Google OAuth
Open:

```
/auth/google
```

Example:

```
http://127.0.0.1:7860/auth/google
```

Log in and allow calendar permissions.

---

### Step 3 — Start booking with voice
Hold the microphone button and speak naturally, for example:

> "Hi, I want to book a meeting."  
> "My name is Chang Shen."  
> "My email is sc2000925@gmail.com."  
> "My phone number is 0403 381 975."  
> "Next Monday at 2pm."  
> "Yes, that’s correct."

---

### Step 4 — Confirm event creation
When the agent repeats the details, say:

> "Yes"

The agent will respond with:

- Meet link
- Calendar link
- Invite confirmation

---

## 🖥️ Run Locally (Optional)

### 1. Clone repository
```bash
cd Voice-Scheduling-Agent
```

### 2. Create `.env`
Create a `.env` file in the project root:

```env
# =========================
# OpenAI
# =========================
OPENAI_API_KEY=YOUR_OPENAI_KEY
CHAT_MODEL=gpt-4.1-nano
ASR_MODEL=whisper-1

# =========================
# Google OAuth (Calendar API)
# =========================
GOOGLE_CLIENT_ID=YOUR_GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET=YOUR_GOOGLE_CLIENT_SECRET
GOOGLE_REDIRECT_URI=http://127.0.0.1:7860/google/callback

# =========================
# Calendar Settings
# =========================
CALENDAR_ID=primary
TZ_NAME=America/Los_Angeles
MEETING_DURATION_MIN=30
DEFAULT_TITLE=Scheduled Meeting

# =========================
# Server
# =========================
PORT=7860
HOST=0.0.0.0

# =========================
# TTS Settings
# =========================
TTS_MODEL=gpt-4o-mini-tts
TTS_VOICE=alloy
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Run server
```bash
python app.py
```

Server will run at:
```
http://127.0.0.1:7860
```

---

## 📦 Deployment (Zeabur)

This project is designed for easy deployment on **Zeabur**.

### Key Deployment Notes
When deploying, ensure the following environment variables are set:

- `OPENAI_API_KEY`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI`

The redirect URI must match exactly what is configured in Google Cloud Console:

Also make sure the domain is added to:
- OAuth consent screen → Authorized domains
- OAuth client → Authorized redirect URIs

---

## 📸 Proof of Event Creation

Screenshots or logs should be included in `/screenshots/`:

- `voice_ui.png`
- `calendar_event_created.png`

Optional: Loom video showing:
- Voice booking
- Confirmation step
- Calendar event created successfully
- Google Meet link generated

---

## 🔥 Key Implementation Notes

### Why SSE instead of WebSocket?
SSE provides a lightweight and reliable way to stream assistant responses token-by-token, while remaining deployment-friendly.

### Why OpenAI TTS?
OpenAI TTS provides natural voice output and supports streaming MP3 response efficiently.

### Why LLM-based extraction?
Instead of relying on brittle regex rules, the system uses the LLM to extract structured meeting details from the full conversation history, making the agent robust to accents and natural language variations.

---

## 🛠 Future Improvements (Planned Roadmap)

This prototype is production-oriented, and the next iteration would include:

### 1. Email sending (meeting link delivery)
- Send confirmation email containing Meet link + calendar link
- SMTP or SendGrid integration

### 2. SMS integration
- Send meeting link via SMS (Twilio / AWS SNS)

### 3. Interruptions (barge-in)
- Allow user to interrupt assistant mid-speech
- Stop TTS stream instantly and resume listening

### 4. Silence detection / auto-stop recording
- Automatically stop recording when user pauses
- Improves UX for mobile users

### 5. Multi-turn correction support
Example:
> "Actually make it 3pm instead."

---

## 📂 Project Structure

```
Voice-Scheduling-Agent/
│
├── app.py
├── voice.py
├── chat.py
├── oauth_google.py
├── calendar_event.py
├── requirements.txt
├── templates/
│   ├── voice.html
│   └── chat.html
└── screenshot/
    ├── calendar_event_created.png
```

---

## 🧾 Requirements Checklist (Assignment)

✅ Initiates a conversation  
✅ Collects name, time, title  
✅ Confirms final details  
✅ Creates real calendar event  
✅ Generates meeting link  
✅ Deployed and accessible via hosted URL  
✅ README with testing instructions  
✅ Optional local run instructions  
✅ Calendar integration explained  
✅ Streaming response + streaming TTS  

---

## 👤 Author

**Chang Shen**  
AI / ML Engineer  
Melbourne, Australia  
Email: sc2000925@gmail.com  

---

## License

MIT License (for demo purposes).
