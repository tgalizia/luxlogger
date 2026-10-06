# Specification Document: Luxtronik 2.0 AI Advisor & Monitor (MVP Local Prototype)

## 1. Project Goal
Build a local Python prototype to connect to an Alpha Innotech heat pump equipped with a Luxtronik 2.0/2.1 controller (listening on local TCP port 8888). 
The application must:
1. Connect via TCP socket to fetch real-time telemetry from the heat pump.
2. Store time-series telemetry data and manual indoor temperature inputs into a local SQLite database.
3. Expose a simple, lightweight Python web interface (FastAPI + Jinja2/HTML or Streamlit) without authentication.
4. Integrate an AI Engine (using OpenAI / Gemini / Claude API) that analyzes heat pump metrics (short-cycling, compressor runtime, backup heater usage, flow/return temperatures) and provides natural language optimization suggestions.
5. Keep the code architecture modular and REST-ready so the backend can seamlessly serve a React frontend and migrate to PostgreSQL/Supabase in Phase 2.

---

## 2. Tech Stack (Phase 1)
- **Language**: Python 3.10+
- **Database**: SQLite (`luxtronik_data.db`) via `SQLAlchemy` or `sqlite3`
- **Heat Pump Driver**: `luxtronik` Python library (TCP port 8888)
- **Web Framework / UI**: FastAPI + Jinja2 Templates (or Streamlit)
- **AI Integration**: OpenAI SDK / Google GenAI SDK
- **Data Visualization**: Chart.js (if HTML template) or Plotly

---

## 3. Project Structure
```text
luxtronik-ai-advisor/
├── app/
│   ├── __init__.py
│   ├── config.py              # Environment variables & configuration
│   ├── database.py            # SQLite connection and ORM models
│   ├── luxtronik_client.py    # Luxtronik TCP reader service
│   ├── ai_advisor.py          # LLM prompt engineering & diagnostic logic
│   ├── main.py                # Web server / API routes
│   └── templates/             # HTML templates for simple UI
│       └── index.html
├── data/
│   └── luxtronik_data.db      # SQLite database file
├── requirements.txt
├── README.md
└── .env