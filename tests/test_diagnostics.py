"""Diagnostics for compressor cycles and backup-heater time."""

from datetime import datetime, timedelta

from app.diagnostics import HEATER_STAGE, Reading, analyze

START = datetime(2026, 10, 5, 12, 0, 0)


def at(minutes, **kwargs):
    return Reading(recorded_at=START + timedelta(minutes=minutes), **kwargs)


def test_short_cycle_is_counted_when_runtime_resets_early():
    readings = [
        at(0, compressor_running=False, compressor_runtime_s=0),
        at(1, compressor_running=True, compressor_runtime_s=60),
        at(2, compressor_running=True, compressor_runtime_s=120),
        at(3, compressor_running=True, compressor_runtime_s=180),
        at(4, compressor_running=False, compressor_runtime_s=0),
    ]
    result = analyze(readings, short_cycle_seconds=600)
    assert result["compressor_starts"] == 1
    assert result["completed_cycles"] == 1
    assert result["short_cycles"] == 1
    assert result["cycle_lengths_s"] == [180]


def test_long_cycle_is_not_short_and_open_cycle_is_ignored():
    finished = [
        at(0, compressor_running=False, compressor_runtime_s=0),
        at(10, compressor_running=True, compressor_runtime_s=600),
        at(20, compressor_running=True, compressor_runtime_s=1200),
        at(25, compressor_running=True, compressor_runtime_s=1500),
        at(26, compressor_running=False, compressor_runtime_s=0),
    ]
    result = analyze(finished, short_cycle_seconds=600)
    assert result["short_cycles"] == 0
    assert result["cycle_lengths_s"] == [1500]

    still_running = [
        at(0, compressor_running=False, compressor_runtime_s=0),
        at(1, compressor_running=True, compressor_runtime_s=100),
        at(2, compressor_running=True, compressor_runtime_s=200),
    ]
    assert analyze(still_running)["completed_cycles"] == 0
    assert analyze(still_running)["short_cycles"] == 0


def test_backup_heater_uses_counter_when_it_advances():
    readings = [
        at(0, backup_heater_total_s=1000, bivalence_stage="one compressor allowed to run"),
        at(2, backup_heater_total_s=1180, bivalence_stage="one compressor allowed to run"),
    ]
    assert analyze(readings)["backup_heater_on_time_s"] == 180


def test_backup_heater_uses_stage_or_session_timer_without_a_moving_counter():
    staged = [
        at(0, bivalence_stage=HEATER_STAGE, backup_heater_total_s=10),
        at(2, bivalence_stage=HEATER_STAGE, backup_heater_total_s=10),
    ]
    assert analyze(staged)["backup_heater_on_time_s"] == 120

    timer = [
        at(0, bivalence_stage="one compressor allowed to run", backup_heater_runtime_s=10),
        at(1, bivalence_stage="one compressor allowed to run", backup_heater_runtime_s=70),
    ]
    assert analyze(timer)["backup_heater_on_time_s"] == 60


def test_compressor_on_time_and_temperature_means():
    counted = [
        at(0, compressor_running=False, compressor_total_s=0, flow_temp=35, return_temp=30, return_setpoint=30),
        at(5, compressor_running=False, compressor_total_s=90, flow_temp=36, return_temp=30, return_setpoint=30),
    ]
    result = analyze(counted, indoor_c=21.5, indoor_room="living room")
    assert result["compressor_on_time_s"] == 90
    assert result["mean_flow_return_delta_c"] == 5.5
    assert result["mean_return_minus_setpoint_c"] == 0
    assert result["latest_indoor_c"] == 21.5
    assert result["latest_indoor_room"] == "living room"

    integrated = [
        at(0, compressor_running=True),
        at(1, compressor_running=True),
    ]
    assert analyze(integrated)["compressor_on_time_s"] == 60


def test_empty_window():
    result = analyze([])
    assert result["sample_count"] == 0
    assert result["short_cycles"] == 0
    assert result["compressor_on_time_s"] == 0
    assert result["mean_flow_return_delta_c"] is None
