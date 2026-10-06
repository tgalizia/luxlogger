# Luxtronik AI Advisor

Local, read-only monitor for an Alpha Innotec heat pump with a Luxtronik 2.0/2.1 controller. It polls the controller over TCP, stores telemetry and manual room temperatures in SQLite, and asks an LLM for optimization suggestions grounded in those measurements.

The process never calls `Luxtronik.write()`. It cannot change setpoints or parameters on the heat pump.

## Requirements

- Python 3.10 or newer
- The heat pump reachable on your LAN, or demo mode

Port **8888** is the controller socket on firmware older than 1.76. Firmware 1.76 and later listen on **8889**. Set `LUXTRONIK_PORT` to match the unit.

## Run

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`: set `LUXTRONIK_HOST` to the heat pump address and add one API key (`OPENAI_API_KEY`, `GEMINI_API_KEY`, or `ANTHROPIC_API_KEY`). `AI_PROVIDER` selects `openai` (default), `gemini`, or `anthropic`.

```bash
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000

Set `DEMO_MODE=true` to fill the database with synthetic samples when the controller is not on the network. The dashboard, chart, and advisor still run.

## Docker

Local development uses the Compose file in this repo. The service reloads when files under `app/` change and listens on port 8001.

```bash
cp .env.example .env
docker compose up --build
```

Open http://127.0.0.1:8001

## Raspberry Pi

A push to `main` updates the Pi at http://192.168.1.29. The app runs there under systemd, from `/opt/luxlogger`, without Docker. `.env` and `data/` stay on the Pi and are not committed.

## What is stored

`data/luxtronik_data.db` holds:

- `telemetry_samples` — flow, return, outdoor, and hot-water temperatures, compressor state, and backup-heater stage
- `indoor_temperatures` — room readings you type in
- `advisor_reports` — the diagnostics JSON and the suggestion text

`DATABASE_URL` is a SQLAlchemy URL. Point it at PostgreSQL later without changing the models. The JSON routes under `/api` are what a later React client would call.

## API

- `GET /api/status` — connection health and the latest sample
- `GET /api/telemetry?hours=24`
- `POST /api/indoor` — `{ "temperature_c": 21.5, "room": "living room" }`
- `GET /api/indoor`
- `POST /api/advice` — diagnostics for the window, then a model suggestion
- `GET /api/advice/latest`

## Tests

```bash
pytest
```

The tests cover short-cycle detection and backup-heater time. They do not open a socket or call a model.
