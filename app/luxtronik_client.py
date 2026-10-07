"""Luxtronik TCP client, demo sample generator, and one confirmed setting write.

Telemetry reads never call write(). A setting changes only through write_setting().
"""

import logging
import math
import socket
import struct
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

from app.config import get_settings
from app.database import add_sample, count_samples, session_scope, utcnow
from app.settings_catalog import (
    SETTINGS,
    format_value,
    get_spec,
    present,
    validate_value,
    values_match,
)

logger = logging.getLogger("luxtronik_advisor")

COMPRESSOR_MODES = {"heating", "hot water", "swimming pool/solar", "defrost", "cooling"}
HEATER_STAGE = "additional heat generator allowed to run"
COMPRESSOR_STAGE = "one compressor allowed to run"
SOCKET_TIMEOUT_SECONDS = 8
LONG_ON_SECONDS = 25 * 60
SHORT_ON_SECONDS = 4 * 60


@dataclass
class Snapshot:
    recorded_at: datetime
    flow_temp: float | None
    return_temp: float | None
    outdoor_temp: float | None
    dhw_temp: float | None
    dhw_setpoint: float | None
    return_setpoint: float | None
    flow_rate: float | None
    heatpump_code: str | None
    operating_mode: str | None
    compressor_hz: float | None
    compressor_runtime_s: float | None
    compressor_total_s: float | None
    compressor_running: bool
    bivalence_stage: str | None
    backup_heater_runtime_s: float | None
    backup_heater_total_s: float | None
    backup_heater_running: bool | None
    status_line: str | None
    heat_heating_kwh: float | None = None
    heat_dhw_kwh: float | None = None
    heat_pool_kwh: float | None = None


class QueriesPaused(Exception):
    """The controller socket is left alone while queries are paused."""


class PollState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.connected = False
        self.polling = True
        self.last_error: str | None = None
        self.last_success_at: datetime | None = None
        self.next_poll_at: datetime | None = None

    def set_polling(self, enabled: bool) -> bool:
        with self._lock:
            self.polling = bool(enabled)
            return self.polling

    def is_polling(self) -> bool:
        with self._lock:
            return self.polling

    def schedule_next(self, when: datetime) -> None:
        with self._lock:
            self.next_poll_at = when

    def mark_ok(self, when: datetime) -> None:
        with self._lock:
            self.connected = True
            self.last_error = None
            self.last_success_at = when

    def mark_error(self, message: str) -> None:
        with self._lock:
            self.connected = False
            self.last_error = message

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "connected": self.connected,
                "polling": self.polling,
                "last_error": self.last_error,
                "last_success_at": self.last_success_at,
                "next_poll_at": self.next_poll_at,
            }


def ensure_polling() -> None:
    """Refuse a controller socket when the dashboard has paused queries."""
    if not poll_state.is_polling():
        raise QueriesPaused("Controller queries are paused.")


poll_state = PollState()
_seeded = False
_seed_lock = threading.Lock()


def poll_once() -> None:
    """Read one sample and store it. Failures stay on poll_state for the UI."""
    if not poll_state.is_polling():
        return
    settings = get_settings()
    if settings.demo_mode:
        _seed_demo_once(settings.poll_interval_seconds)
    from app.runtime import controller_endpoint

    host, port = controller_endpoint()
    recorded_at = utcnow()
    try:
        if settings.demo_mode:
            snapshot = demo_snapshot(recorded_at)
        else:
            snapshot = read_live_snapshot(host, port, recorded_at)
    except (OSError, ConnectionError, TimeoutError, struct.error) as exc:
        poll_state.mark_error(str(exc) or exc.__class__.__name__)
        logger.warning("Luxtronik read failed: %s", exc)
        return
    except Exception as exc:
        poll_state.mark_error(str(exc) or exc.__class__.__name__)
        logger.exception("Luxtronik read failed")
        return
    with session_scope() as session:
        add_sample(session, snapshot)
    poll_state.mark_ok(recorded_at)
    logger.info(
        "Stored sample mode=%s compressor=%s flow=%s",
        snapshot.operating_mode,
        snapshot.compressor_running,
        snapshot.flow_temp,
    )


def read_controller_identity(host: str, port: int) -> dict:
    """Read the pump series code and controller software. Does not write."""
    from luxtronik import Luxtronik

    previous_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(SOCKET_TIMEOUT_SECONDS)
    try:
        pump = Luxtronik(host, port)
        calculations = pump.calculations
    finally:
        socket.setdefaulttimeout(previous_timeout)
    return {
        "pump_model": _text(calculations, "ID_WEB_Code_WP_akt"),
        "controller_software": _text(calculations, "ID_WEB_SoftStand"),
    }


def read_live_snapshot(host: str, port: int, recorded_at: datetime) -> Snapshot:
    """Open the config socket, read calculations, and close. Does not write."""
    from luxtronik import Luxtronik

    previous_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(SOCKET_TIMEOUT_SECONDS)
    try:
        pump = Luxtronik(host, port)
    finally:
        socket.setdefaulttimeout(previous_timeout)

    calculations = pump.calculations
    status_line = _text(calculations, "ID_WEB_HauptMenuStatus_Zeile1")
    operating_mode = _text(calculations, "ID_WEB_WP_BZ_akt")
    frequency = _number(calculations, "ID_WEB_Freq_VD")
    runtime = _number(calculations, "ID_WEB_Time_WPein_akt")
    compressor_output = _bool(calculations, "ID_WEB_VD1out")
    heater_runtime = _number(calculations, "ID_WEB_Time_ZWE1_akt")
    return Snapshot(
        recorded_at=recorded_at,
        flow_temp=_number(calculations, "ID_WEB_Temperatur_TVL"),
        return_temp=_number(calculations, "ID_WEB_Temperatur_TRL"),
        outdoor_temp=_number(calculations, "ID_WEB_Temperatur_TA"),
        dhw_temp=_number(calculations, "ID_WEB_Temperatur_TBW"),
        dhw_setpoint=_number(calculations, "ID_WEB_Einst_BWS_akt"),
        return_setpoint=_number(calculations, "ID_WEB_Sollwert_TRL_HZ"),
        flow_rate=_number(calculations, "ID_WEB_WMZ_Durchfluss"),
        heatpump_code=_text(calculations, "ID_WEB_Code_WP_akt"),
        operating_mode=operating_mode,
        compressor_hz=frequency,
        compressor_runtime_s=runtime,
        compressor_total_s=_number(calculations, "ID_WEB_Zaehler_BetrZeitVD1"),
        compressor_running=derive_compressor_running(
            status_line, compressor_output, frequency, runtime, operating_mode
        ),
        bivalence_stage=_text(calculations, "ID_WEB_BIV_Stufe_akt"),
        backup_heater_runtime_s=heater_runtime,
        backup_heater_total_s=_number(calculations, "ID_WEB_Zaehler_BetrZeitZWE1"),
        backup_heater_running=derive_heater_running(
            _bool(calculations, "ID_WEB_ZW1out"),
            _bool(calculations, "ID_WEB_ZW2SSTout"),
            _bool(calculations, "ID_WEB_ZW3SSTout"),
            runtime=heater_runtime,
        ),
        status_line=status_line,
        heat_heating_kwh=_number(calculations, "ID_WEB_WMZ_Heizung"),
        heat_dhw_kwh=_number(calculations, "ID_WEB_WMZ_Brauchwasser"),
        heat_pool_kwh=_number(calculations, "ID_WEB_WMZ_Schwimmbad"),
    )


def derive_heater_running(*outputs: bool | None, runtime: float | None) -> bool:
    """True when any extra-heater output is closed, else when its session timer is counting."""
    known = [value for value in outputs if value is not None]
    if known:
        return any(known)
    return runtime is not None and runtime > 0


def derive_compressor_running(status_line, compressor_output, frequency, runtime, operating_mode) -> bool:
    if status_line == "heatpump idle":
        return False
    if status_line == "heatpump running" or compressor_output is True:
        return True
    if frequency is not None and frequency > 0:
        return True
    if status_line == "defrost":
        return True
    if operating_mode in COMPRESSOR_MODES and runtime is not None and runtime > 0:
        return True
    return False


def demo_snapshot(recorded_at: datetime) -> Snapshot:
    """Plausible Luxtronik values, including short cycles and backup-heater hours."""
    epoch = _epoch(recorded_at)
    hour_index = epoch // 3600
    second_in_hour = epoch % 3600
    hour_of_day = hour_index % 24
    on_limit = SHORT_ON_SECONDS if hour_index % 5 == 0 else LONG_ON_SECONDS
    running = second_in_hour < on_limit
    outdoor = round(_outdoor_raw(hour_of_day), 1)
    heater_on = hour_of_day in HEATER_HOURS
    heat_heating_kwh, heat_dhw_kwh, heat_pool_kwh = _demo_heat_kwh(epoch)
    return Snapshot(
        recorded_at=recorded_at.replace(tzinfo=None) if recorded_at.tzinfo else recorded_at,
        flow_temp=36.0 if running else 27.5,
        return_temp=31.0 if running else 26.8,
        outdoor_temp=outdoor,
        dhw_temp=46.5,
        dhw_setpoint=48.0,
        return_setpoint=30.0,
        flow_rate=980.0 if running else 220.0,
        heatpump_code="LWC",
        operating_mode="heating" if running else "no request",
        compressor_hz=48.0 if running else 0.0,
        compressor_runtime_s=float(second_in_hour if running else 0),
        compressor_total_s=float(_compressor_total(epoch)),
        compressor_running=running,
        bivalence_stage=HEATER_STAGE if heater_on else COMPRESSOR_STAGE,
        backup_heater_runtime_s=float(second_in_hour if heater_on else 0),
        backup_heater_total_s=float(_heater_total(epoch)),
        backup_heater_running=heater_on,
        status_line="heatpump running" if running else "heatpump idle",
        heat_heating_kwh=heat_heating_kwh,
        heat_dhw_kwh=heat_dhw_kwh,
        heat_pool_kwh=heat_pool_kwh,
    )


def _seed_demo_once(interval_seconds: int) -> None:
    global _seeded
    with _seed_lock:
        if _seeded:
            return
        with session_scope() as session:
            if count_samples(session) == 0:
                _insert_demo_history(session, utcnow(), interval_seconds)
        _seeded = True


def _insert_demo_history(session, now: datetime, interval_seconds: int, hours: int = 24) -> None:
    span = hours * 3600
    step = interval_seconds
    if span / step > 2000:
        step = math.ceil(span / 2000)
    start = _epoch(now) - span
    end = _epoch(now)
    stamp = start
    while stamp < end:
        recorded_at = datetime.fromtimestamp(stamp, timezone.utc).replace(tzinfo=None)
        add_sample(session, demo_snapshot(recorded_at))
        stamp += step


def _epoch(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp())


def _outdoor_raw(hour_of_day: int) -> float:
    return 5 + 6 * math.sin(2 * math.pi * (hour_of_day - 8) / 24)


HEATER_HOURS = {hour for hour in range(24) if _outdoor_raw(hour) < 1.0}


def _compressor_total(epoch: int) -> int:
    hour_index = epoch // 3600
    second_in_hour = epoch % 3600
    groups = hour_index // 5
    per_group = SHORT_ON_SECONDS + 4 * LONG_ON_SECONDS
    total = groups * per_group
    for hour in range(groups * 5, hour_index):
        total += SHORT_ON_SECONDS if hour % 5 == 0 else LONG_ON_SECONDS
    on_limit = SHORT_ON_SECONDS if hour_index % 5 == 0 else LONG_ON_SECONDS
    return total + min(second_in_hour, on_limit)


DEMO_HEAT_WATTS = 4000
DEMO_HEAT_EPOCH = 1_704_067_200  # 2024-01-01 UTC, so the meter stays in a household range


def _demo_heat_kwh(epoch: int) -> tuple[float, float, float]:
    """Thermal kWh grown from compressor on-time: mostly heating, some hot water."""
    elapsed = max(0, epoch - DEMO_HEAT_EPOCH)
    thermal = _compressor_total(elapsed) * DEMO_HEAT_WATTS / 3_600_000
    return round(thermal * 0.75, 1), round(thermal * 0.25, 1), 0.0


def _heater_total(epoch: int) -> int:
    hour_index = epoch // 3600
    second_in_hour = epoch % 3600
    days = hour_index // 24
    total = days * len(HEATER_HOURS) * 3600
    hour_of_day = hour_index % 24
    total += sum(3600 for hour in range(hour_of_day) if hour in HEATER_HOURS)
    if hour_of_day in HEATER_HOURS:
        total += second_in_hour
    return total


def _raw(calculations, name: str):
    try:
        field = calculations.get(name)
    except Exception:
        logger.debug("Missing calculation %s", name, exc_info=True)
        return None
    if field is None or not hasattr(field, "value"):
        return None
    return field.value


def _number(calculations, name: str) -> float | None:
    value = _raw(calculations, name)
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(calculations, name: str) -> str | None:
    value = _raw(calculations, name)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _bool(calculations, name: str) -> bool | None:
    value = _raw(calculations, name)
    if isinstance(value, bool):
        return value
    return None


class SettingsWriteError(Exception):
    """A parameter write did not stick, or the controller rejected it."""


def read_settings(host: str, port: int) -> list[dict]:
    """Read the four household settings. Does not write."""
    return _with_pump(host, port, _read_allowed)


def write_setting(host: str, port: int, setting_id: str, value) -> dict:
    """Validate one allowlisted parameter, write it, and read it back."""
    return _with_pump(host, port, lambda pump: commit_setting(pump, setting_id, value))


def commit_setting(pump, setting_id: str, value) -> dict:
    """Set one parameter on an already open pump and require the read-back to match."""
    spec = get_spec(setting_id)
    current = _read_parameter(pump, spec.id)
    normalized = validate_value(spec.id, value, current)
    if values_match(spec.id, current, normalized):
        return {
            "changed": False,
            "old_value": format_value(spec.id, current),
            "new_value": format_value(spec.id, normalized),
            "setting": present(spec, current),
        }
    pump.parameters.queue.clear()
    pump.parameters.set(spec.id, normalized)
    queued = [item for item in pump.parameters.queue.values() if isinstance(item, int)]
    if len(pump.parameters.queue) != 1 or len(queued) != 1:
        pump.parameters.queue.clear()
        raise SettingsWriteError(f"The controller did not accept {spec.label}.")
    pump.write()
    pump.read()
    confirmed = _read_parameter(pump, spec.id)
    if not values_match(spec.id, confirmed, normalized):
        raise SettingsWriteError(
            f"{spec.label} is still {format_value(spec.id, confirmed)} after the write."
        )
    return {
        "changed": True,
        "old_value": format_value(spec.id, current),
        "new_value": format_value(spec.id, confirmed),
        "setting": present(spec, confirmed),
    }


def _with_pump(host: str, port: int, action):
    from luxtronik import Luxtronik

    previous_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(SOCKET_TIMEOUT_SECONDS)
    try:
        pump = Luxtronik(host, port, safe=True)
        return action(pump)
    finally:
        socket.setdefaulttimeout(previous_timeout)


def _read_allowed(pump) -> list[dict]:
    rows = []
    for spec in SETTINGS:
        value = _read_parameter(pump, spec.id)
        rows.append(present(spec, value))
    return rows


def _read_parameter(pump, setting_id: str):
    spec = get_spec(setting_id)
    field = pump.parameters.get(setting_id)
    if field is None or field.value is None:
        raise SettingsWriteError(f"{spec.label} was not returned by the controller.")
    if spec.kind == "choice":
        return str(field.value).strip()
    try:
        return round(float(field.value), 1)
    except (TypeError, ValueError) as exc:
        raise SettingsWriteError(f"{spec.label} was not returned by the controller.") from exc
