"""FastAPI routes, dashboard, and the background Luxtronik poller."""

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.requests import Request
from sqlalchemy.orm import Session

from app.ai_advisor import AdvisorError, advise, suggest_settings
from app.config import PROJECT_ROOT, get_settings
from app.database import (
    add_indoor,
    add_report,
    get_app_preference,
    get_db,
    init_db,
    isoformat_utc,
    latest_indoor,
    latest_report,
    latest_sample,
    indoor_since,
    preference_to_dict,
    recent_indoor,
    report_to_dict,
    sample_to_dict,
    samples_since,
    save_app_preference,
    utcnow,
    indoor_to_dict,
    add_setting_change,
)
from app.energy import PriceError, energy_report, validate_currency, validate_price
from app.diagnostics import analyze, reading_from_sample
from app.mode_status import describe_mode, mode_badges
from app.luxtronik_client import (
    QueriesPaused,
    SettingsWriteError,
    ensure_polling,
    poll_once,
    poll_state,
    read_settings,
    write_setting,
)
from app.settings_catalog import SettingsError, validate_value

logger = logging.getLogger("luxtronik_advisor")
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "app" / "templates"))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    init_db()
    stop = asyncio.Event()
    await asyncio.to_thread(poll_once)
    task = asyncio.create_task(_poll_loop(stop))
    yield
    stop.set()
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="Luxtronik AI Advisor", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(PROJECT_ROOT / "app" / "static")), name="static")


class IndoorIn(BaseModel):
    temperature_c: float = Field(..., ge=-10, le=45)
    room: str = Field(default="living room", max_length=80)


class ApplyIn(BaseModel):
    id: str
    value: str | float | int
    from_suggestion: bool = False


class PollingIn(BaseModel):
    enabled: bool


class AppSettingsIn(BaseModel):
    price_per_kwh: str
    currency: str | None = None


async def _poll_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        interval = get_settings().poll_interval_seconds
        due = datetime.now(timezone.utc) + timedelta(seconds=interval)
        poll_state.schedule_next(due)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            await asyncio.to_thread(poll_once)


def _page(request: Request, template: str, active: str):
    return templates.TemplateResponse(
        request,
        template,
        {
            "active": active,
            "refresh_seconds": get_settings().poll_interval_seconds,
        },
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(PROJECT_ROOT / "app" / "static" / "favicon.ico")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return _page(request, "index.html", "dashboard")


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    return _page(request, "settings.html", "settings")


@app.get("/app-settings", response_class=HTMLResponse)
def app_settings_page(request: Request):
    return _page(request, "app_settings.html", "app")


@app.get("/api/status")
def status(session: Session = Depends(get_db)):
    settings = get_settings()
    health = poll_state.snapshot()
    latest = latest_sample(session)
    indoor = latest_indoor(session)
    latest_payload = None if latest is None else sample_to_dict(latest)
    if latest_payload is not None:
        latest_payload["mode_text"] = describe_mode(
            latest_payload["operating_mode"], latest_payload["status_line"]
        )
        latest_payload["mode_badges"] = mode_badges(
            latest_payload["operating_mode"], latest_payload["status_line"]
        )
    return {
        "connected": health["connected"],
        "polling": health["polling"],
        "demo_mode": settings.demo_mode,
        "host": settings.luxtronik_host,
        "port": settings.luxtronik_port,
        "last_error": health["last_error"],
        "poll_interval_seconds": settings.poll_interval_seconds,
        "next_poll_at": isoformat_utc(health["next_poll_at"]),
        "last_success_at": isoformat_utc(health["last_success_at"]),
        "latest": latest_payload,
        "indoor": None if indoor is None else indoor_to_dict(indoor),
    }


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


@app.get("/api/telemetry")
def telemetry(
    hours: int = Query(default=24, ge=1, le=168),
    since: datetime | None = Query(default=None),
    session: Session = Depends(get_db),
):
    start = utcnow() - timedelta(hours=hours)
    if since is not None:
        start = _naive_utc(since)
        if utcnow() - start > timedelta(days=370):
            raise HTTPException(status_code=400, detail="Choose a range within the last year.")
    rows = samples_since(session, start)
    return {"since": isoformat_utc(start), "samples": [sample_to_dict(row) for row in rows]}


@app.get("/api/energy")
def energy(
    since: datetime | None = Query(default=None),
    session: Session = Depends(get_db),
):
    start = utcnow() - timedelta(hours=24)
    if since is not None:
        start = _naive_utc(since)
        if utcnow() - start > timedelta(days=370):
            raise HTTPException(status_code=400, detail="Choose a range within the last year.")
    preference = preference_to_dict(get_app_preference(session))
    return energy_report(
        samples_since(session, start),
        latest_sample(session),
        preference["price_per_kwh"],
        preference["currency"],
        isoformat_utc(start),
    )


@app.get("/api/app-settings")
def read_app_settings(session: Session = Depends(get_db)):
    return preference_to_dict(get_app_preference(session))


@app.put("/api/app-settings")
def update_app_settings(body: AppSettingsIn, session: Session = Depends(get_db)):
    try:
        price = validate_price(body.price_per_kwh)
        currency = validate_currency(body.currency)
    except PriceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    row = save_app_preference(session, price, currency)
    session.flush()
    return preference_to_dict(row)


@app.get("/api/indoor")
def list_indoor(
    limit: int = Query(default=48, ge=1, le=5000),
    since: datetime | None = Query(default=None),
    session: Session = Depends(get_db),
):
    if since is not None:
        rows = indoor_since(session, _naive_utc(since))
    else:
        rows = recent_indoor(session, limit)
    return {"readings": [indoor_to_dict(row) for row in rows]}


@app.post("/api/indoor")
def create_indoor(body: IndoorIn, session: Session = Depends(get_db)):
    room = body.room.strip() or "living room"
    row = add_indoor(session, room, body.temperature_c)
    session.flush()
    return indoor_to_dict(row)


@app.get("/api/advice/latest")
def advice_latest(session: Session = Depends(get_db)):
    row = latest_report(session)
    return {"report": None if row is None else report_to_dict(row)}


@app.post("/api/advice")
def create_advice(
    hours: int | None = Query(default=None, ge=1, le=168),
    session: Session = Depends(get_db),
):
    settings = get_settings()
    window = hours or settings.advice_window_hours
    since = utcnow() - timedelta(hours=window)
    rows = samples_since(session, since)
    if not rows:
        raise HTTPException(status_code=400, detail="No telemetry in the selected window yet.")
    indoor = latest_indoor(session)
    findings = analyze(
        [reading_from_sample(row) for row in rows],
        short_cycle_seconds=settings.short_cycle_seconds,
        indoor_c=None if indoor is None else indoor.temperature_c,
        indoor_room=None if indoor is None else indoor.room,
    )
    findings["window_hours"] = window
    try:
        provider, model, suggestion = advise(findings, settings)
    except AdvisorError as exc:
        raise HTTPException(status_code=503, detail={"message": str(exc), "findings": findings}) from exc
    except Exception as exc:
        logger.exception("Advice request failed")
        raise HTTPException(
            status_code=502,
            detail={"message": f"The model request failed: {exc}", "findings": findings},
        ) from exc
    row = add_report(session, provider, model, findings, suggestion)
    session.flush()
    return report_to_dict(row)


@app.post("/api/polling")
async def update_polling(body: PollingIn, session: Session = Depends(get_db)):
    enabled = poll_state.set_polling(body.enabled)
    logger.info("Controller queries %s", "enabled" if enabled else "paused")
    if enabled:
        await asyncio.to_thread(poll_once)
    return status(session)


def _controller():
    try:
        ensure_polling()
    except QueriesPaused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    settings = get_settings()
    if settings.demo_mode:
        raise HTTPException(status_code=409, detail="Settings are unavailable in demo mode.")
    return settings


def _diagnostics(session: Session, settings) -> dict:
    since = utcnow() - timedelta(hours=settings.advice_window_hours)
    rows = samples_since(session, since)
    if not rows:
        raise HTTPException(status_code=400, detail="No telemetry in the selected window yet.")
    indoor = latest_indoor(session)
    findings = analyze(
        [reading_from_sample(row) for row in rows],
        short_cycle_seconds=settings.short_cycle_seconds,
        indoor_c=None if indoor is None else indoor.temperature_c,
        indoor_room=None if indoor is None else indoor.room,
    )
    findings["window_hours"] = settings.advice_window_hours
    return findings


@app.get("/api/settings")
def list_settings():
    settings = _controller()
    try:
        rows = read_settings(settings.luxtronik_host, settings.luxtronik_port)
    except (OSError, TimeoutError) as exc:
        raise HTTPException(status_code=503, detail=f"Could not reach the controller: {exc}") from exc
    except SettingsWriteError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"settings": rows}


@app.post("/api/settings/suggest")
def create_suggestions(session: Session = Depends(get_db)):
    settings = _controller()
    findings = _diagnostics(session, settings)
    try:
        current = read_settings(settings.luxtronik_host, settings.luxtronik_port)
    except (OSError, TimeoutError) as exc:
        raise HTTPException(status_code=503, detail=f"Could not reach the controller: {exc}") from exc
    except SettingsWriteError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    try:
        changes = suggest_settings(current, findings, settings)
    except AdvisorError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Setting suggestion failed")
        raise HTTPException(status_code=502, detail=f"The model request failed: {exc}") from exc
    return {"settings": current, "changes": changes}


@app.post("/api/settings/apply")
def apply_setting(body: ApplyIn, session: Session = Depends(get_db)):
    settings = _controller()
    try:
        validate_value(body.id, body.value, body.value)
        result = write_setting(settings.luxtronik_host, settings.luxtronik_port, body.id, body.value)
    except SettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SettingsWriteError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except (OSError, TimeoutError) as exc:
        raise HTTPException(status_code=503, detail=f"Could not reach the controller: {exc}") from exc
    if result["changed"]:
        add_setting_change(
            session,
            body.id,
            result["old_value"],
            result["new_value"],
            body.from_suggestion,
        )
        session.flush()
    return {"changed": result["changed"], "setting": result["setting"]}
