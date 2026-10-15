"""Read-only pump summaries for a bot. Nothing here writes to the controller."""

from datetime import datetime, timedelta, timezone

from app.ai_advisor import limit_findings
from app.config import get_settings
from app.database import (
    get_app_preference,
    indoor_to_dict,
    isoformat_utc,
    latest_indoor,
    latest_sample,
    preference_to_dict,
    sample_to_dict,
    samples_since,
    session_scope,
    utcnow,
)
from app.diagnostics import analyze, reading_from_sample
from app.energy import energy_report
from app.luxtronik_client import (
    QueriesPaused,
    SettingsWriteError,
    ensure_polling,
    poll_state,
    read_settings,
)
from app.mode_status import describe_mode, mode_badges
from app.runtime import controller_endpoint, effective_runtime
from app.settings_catalog import (
    SETTINGS,
    SettingsError,
    filter_changes,
    present,
    validate_value,
    values_match,
)
from app.version import APP_VERSION

MAX_HOURS = 168
MAX_LOOKBACK = timedelta(days=800)
CONFIRM = "Nothing was written. Confirm one change on the Pump settings page."


class AgentDataError(Exception):
    """A bot request cannot be answered from the stored samples."""


def pump_status() -> dict:
    with session_scope() as session:
        return pump_status_report(session)


def behavior(
    hours: int | None = None,
    since: str | None = None,
    until: str | None = None,
) -> dict:
    with session_scope() as session:
        return behavior_report(session, hours=hours, since=since, until=until)


def energy(
    hours: int | None = None,
    since: str | None = None,
    until: str | None = None,
) -> dict:
    with session_scope() as session:
        return energy_summary(session, hours=hours, since=since, until=until)


def household_settings() -> dict:
    with session_scope() as session:
        return household_settings_report(session)


def check_changes(changes: list) -> dict:
    with session_scope() as session:
        return check_changes_report(session, changes)


def pump_status_report(session) -> dict:
    """Same facts as GET /api/status, plus how old the latest sample is."""
    settings = get_settings()
    runtime = effective_runtime(session)
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
        "host": runtime.host,
        "port": runtime.port,
        "last_error": health["last_error"],
        "poll_interval_seconds": settings.poll_interval_seconds,
        "next_poll_at": isoformat_utc(health["next_poll_at"]),
        "last_success_at": isoformat_utc(health["last_success_at"]),
        "latest": latest_payload,
        "latest_age_s": _age_seconds(None if latest is None else latest.recorded_at),
        "indoor": None if indoor is None else indoor_to_dict(indoor),
        "indoor_source": runtime.indoor_source,
        "equipment": runtime.identity(),
        "version": APP_VERSION,
    }


def behavior_report(
    session,
    *,
    hours: int | None = None,
    since: str | None = None,
    until: str | None = None,
) -> dict:
    settings = get_settings()
    start, end, window = _window(hours, since, until, settings.advice_window_hours)
    rows = samples_since(session, start, end)
    if not rows:
        raise AgentDataError("No telemetry in the selected window yet.")
    indoor = latest_indoor(session)
    findings = analyze(
        [reading_from_sample(row) for row in rows],
        short_cycle_seconds=settings.short_cycle_seconds,
        indoor_c=None if indoor is None else indoor.temperature_c,
        indoor_room=None if indoor is None else indoor.room,
    )
    findings["window_hours"] = window
    return limit_findings(findings)


def energy_summary(
    session,
    *,
    hours: int | None = None,
    since: str | None = None,
    until: str | None = None,
) -> dict:
    settings = get_settings()
    start, end, _window_hours = _window(hours, since, until, settings.advice_window_hours)
    preference = preference_to_dict(get_app_preference(session))
    return energy_report(
        samples_since(session, start, end),
        latest_sample(session),
        preference["price_per_kwh"],
        preference["currency"],
        isoformat_utc(start),
    )


def household_settings_report(session) -> dict:
    catalog = [present(spec, None) for spec in SETTINGS]
    if get_settings().demo_mode:
        return {
            "live": False,
            "detail": "Live values are unavailable in demo mode.",
            "settings": catalog,
        }
    try:
        ensure_polling()
        host, port = controller_endpoint(session)
        rows = read_settings(host, port)
    except QueriesPaused as exc:
        return {"live": False, "detail": str(exc), "settings": catalog}
    except (OSError, TimeoutError) as exc:
        return {
            "live": False,
            "detail": f"Could not reach the controller: {exc}",
            "settings": catalog,
        }
    except SettingsWriteError as exc:
        return {"live": False, "detail": str(exc), "settings": catalog}
    return {
        "live": True,
        "detail": "These are the only settings a suggestion may change. Nothing here writes to the controller.",
        "settings": rows,
    }


def check_changes_report(session, changes) -> dict:
    current = household_settings_report(session)
    if not current["live"]:
        return {
            "kept": [],
            "dropped": [],
            "written": False,
            "detail": current["detail"] + " A suggestion cannot be checked until the controller can be read.",
        }
    by_id = {item["id"]: item["value"] for item in current["settings"]}
    return classify_changes(changes, by_id)


def classify_changes(changes, current_by_id: dict) -> dict:
    """Keep the same changes as filter_changes, and say why the rest were dropped."""
    if not isinstance(changes, list):
        return {
            "kept": [],
            "dropped": [{"id": None, "value": None, "reason": "The changes must be a list."}],
            "written": False,
            "detail": CONFIRM,
        }
    kept = filter_changes(changes, current_by_id)
    accepted = {item["id"] for item in kept}
    dropped = []
    seen: set[str] = set()
    for item in changes:
        if not isinstance(item, dict):
            dropped.append(
                {
                    "id": None,
                    "value": None,
                    "reason": "Each change must be an object with id, value, and reason.",
                }
            )
            continue
        setting_id = item.get("id")
        value = item.get("value")
        if not isinstance(setting_id, str) or not setting_id:
            dropped.append({"id": None, "value": value, "reason": "Each change needs a setting id."})
            continue
        if setting_id in seen:
            dropped.append({"id": setting_id, "value": value, "reason": "That setting is already in the list."})
            continue
        seen.add(setting_id)
        if setting_id in accepted:
            continue
        dropped.append(
            {
                "id": setting_id,
                "value": value,
                "reason": _drop_reason(setting_id, value, current_by_id),
            }
        )
    return {"kept": kept, "dropped": dropped, "written": False, "detail": CONFIRM}


def _drop_reason(setting_id: str, value, current_by_id: dict) -> str:
    try:
        canonical = validate_value(setting_id, value, current_by_id.get(setting_id))
    except SettingsError as exc:
        return str(exc)
    if values_match(setting_id, current_by_id.get(setting_id), canonical):
        return "Already set to this value."
    if canonical == "Second heatsource":
        return "Second heatsource cannot be suggested."
    return "The change was not accepted."


def _window(
    hours: int | None,
    since: str | None,
    until: str | None,
    default_hours: int,
) -> tuple[datetime, datetime | None, int]:
    if hours is not None and (isinstance(hours, bool) or not isinstance(hours, int) or hours < 1 or hours > MAX_HOURS):
        raise AgentDataError("Hours must be from 1 to 168.")
    start_at = _parse_when(since, "start")
    end_at = _parse_when(until, "end")
    if start_at is None and end_at is None:
        span = hours if hours is not None else default_hours
        return utcnow() - timedelta(hours=span), None, span
    if start_at is None:
        span = hours if hours is not None else default_hours
        start_at = utcnow() - timedelta(hours=span)
    if utcnow() - start_at > MAX_LOOKBACK:
        raise AgentDataError("Choose a range within the last two years.")
    if end_at is not None and end_at <= start_at:
        raise AgentDataError("The end of the range must be after the start.")
    span_end = end_at if end_at is not None else utcnow()
    window = max(1, round((span_end - start_at).total_seconds() / 3600))
    return start_at, end_at, window


def _parse_when(value: str | None, label: str) -> datetime | None:
    if value is None or not str(value).strip():
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise AgentDataError(f"The {label} must be an ISO timestamp.") from exc
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _age_seconds(recorded_at: datetime | None) -> int | None:
    if recorded_at is None:
        return None
    moment = recorded_at
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return max(0, int((utcnow() - moment).total_seconds()))
