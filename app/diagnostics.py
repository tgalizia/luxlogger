"""Cycle and heater statistics computed from stored samples, without an LLM."""

from dataclasses import dataclass
from datetime import datetime, timezone

HEATER_STAGE = "additional heat generator allowed to run"


@dataclass
class Reading:
    recorded_at: datetime
    flow_temp: float | None = None
    return_temp: float | None = None
    outdoor_temp: float | None = None
    return_setpoint: float | None = None
    compressor_running: bool = False
    compressor_runtime_s: float | None = None
    compressor_total_s: float | None = None
    bivalence_stage: str | None = None
    backup_heater_runtime_s: float | None = None
    backup_heater_total_s: float | None = None
    operating_mode: str | None = None
    status_line: str | None = None


def reading_from_sample(row) -> Reading:
    return Reading(
        recorded_at=row.recorded_at,
        flow_temp=row.flow_temp,
        return_temp=row.return_temp,
        outdoor_temp=row.outdoor_temp,
        return_setpoint=row.return_setpoint,
        compressor_running=bool(row.compressor_running),
        compressor_runtime_s=row.compressor_runtime_s,
        compressor_total_s=row.compressor_total_s,
        bivalence_stage=row.bivalence_stage,
        backup_heater_runtime_s=row.backup_heater_runtime_s,
        backup_heater_total_s=row.backup_heater_total_s,
        operating_mode=row.operating_mode,
        status_line=row.status_line,
    )


def analyze(
    readings: list[Reading],
    *,
    short_cycle_seconds: int = 600,
    indoor_c: float | None = None,
    indoor_room: str | None = None,
) -> dict:
    """Summarize a time-ordered window of heat-pump readings."""
    ordered = sorted(readings, key=lambda reading: reading.recorded_at)
    lengths = _completed_cycle_lengths(ordered)
    compressor_on = _prefer_counter(
        _counter_delta(ordered, "compressor_total_s"),
        _integrate(ordered, lambda earlier, _later: earlier.compressor_running),
    )
    heater_on = _prefer_counter(
        _counter_delta(ordered, "backup_heater_total_s"),
        _integrate(ordered, _heater_interval),
    )
    latest = ordered[-1] if ordered else None
    return {
        "sample_count": len(ordered),
        "window_start": _iso(ordered[0].recorded_at) if ordered else None,
        "window_end": _iso(ordered[-1].recorded_at) if ordered else None,
        "compressor_starts": _compressor_starts(ordered),
        "completed_cycles": len(lengths),
        "short_cycles": sum(1 for length in lengths if length < short_cycle_seconds),
        "short_cycle_threshold_s": short_cycle_seconds,
        "cycle_lengths_s": [round(length) for length in lengths],
        "compressor_on_time_s": compressor_on,
        "backup_heater_on_time_s": heater_on,
        "mean_flow_return_delta_c": _mean(
            reading.flow_temp - reading.return_temp
            for reading in ordered
            if reading.flow_temp is not None and reading.return_temp is not None
        ),
        "mean_return_minus_setpoint_c": _mean(
            reading.return_temp - reading.return_setpoint
            for reading in ordered
            if reading.return_temp is not None and reading.return_setpoint is not None
        ),
        "mean_outdoor_c": _mean(
            reading.outdoor_temp for reading in ordered if reading.outdoor_temp is not None
        ),
        "latest_indoor_c": None if indoor_c is None else round(float(indoor_c), 1),
        "latest_indoor_room": indoor_room,
        "latest_operating_mode": None if latest is None else latest.operating_mode,
        "latest_status": None if latest is None else latest.status_line,
        "latest_bivalence_stage": None if latest is None else latest.bivalence_stage,
    }


def _completed_cycle_lengths(readings: list[Reading]) -> list[float]:
    """A cycle ends when the current compressor runtime counter drops."""
    peak: float | None = None
    lengths: list[float] = []
    for reading in readings:
        runtime = reading.compressor_runtime_s
        if runtime is None:
            continue
        if peak is None:
            peak = runtime
            continue
        if runtime + 1 < peak:
            lengths.append(peak)
            peak = runtime
        else:
            peak = max(peak, runtime)
    return lengths


def _compressor_starts(readings: list[Reading]) -> int:
    starts = 0
    previous: bool | None = None
    for reading in readings:
        if previous is False and reading.compressor_running:
            starts += 1
        previous = reading.compressor_running
    return starts


def _counter_delta(readings: list[Reading], attribute: str) -> float | None:
    values = [getattr(reading, attribute) for reading in readings if getattr(reading, attribute) is not None]
    if len(values) < 2:
        return None
    delta = float(values[-1] - values[0])
    if delta < 0:
        return None
    return delta


def _integrate(readings: list[Reading], active) -> float:
    total = 0.0
    for earlier, later in zip(readings, readings[1:]):
        elapsed = (later.recorded_at - earlier.recorded_at).total_seconds()
        if elapsed <= 0:
            continue
        if active(earlier, later):
            total += elapsed
    return total


def _heater_interval(earlier: Reading, later: Reading) -> bool:
    if earlier.bivalence_stage == HEATER_STAGE or later.bivalence_stage == HEATER_STAGE:
        return True
    if earlier.backup_heater_runtime_s is None or later.backup_heater_runtime_s is None:
        return False
    return later.backup_heater_runtime_s > earlier.backup_heater_runtime_s + 0.5


def _prefer_counter(counter: float | None, integrated: float) -> float:
    if counter is not None and counter > 0:
        return round(counter, 1)
    if integrated > 0:
        return round(integrated, 1)
    if counter is not None:
        return 0.0
    return 0.0


def _mean(values) -> float | None:
    numbers = list(values)
    if not numbers:
        return None
    return round(sum(numbers) / len(numbers), 2)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        return value.isoformat() + "Z"
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
