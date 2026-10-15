"""Read-only bot summaries. These tests do not open a socket or call a model."""

import inspect
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agent_data import (
    AgentDataError,
    behavior_report,
    check_changes_report,
    classify_changes,
    energy_summary,
    household_settings_report,
    pump_status_report,
)
from app.ai_advisor import CYCLE_LENGTH_LIMIT
from app.database import Base, add_indoor, add_sample, utcnow
from app.luxtronik_client import Snapshot, poll_state
from app.mcp_server import mcp
from app.settings_catalog import filter_changes

CURRENT = {
    "ID_Ba_Hz_akt": "Automatic",
    "ID_Ba_Bw_akt": "Automatic",
    "ID_Einst_BWS_akt": 46.0,
    "ID_Einst_WK_akt": 20.0,
}


def memory_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def snap(when, **kwargs):
    fields = dict(
        recorded_at=when,
        flow_temp=35.0,
        return_temp=30.0,
        outdoor_temp=5.0,
        dhw_temp=45.0,
        dhw_setpoint=46.0,
        return_setpoint=30.0,
        flow_rate=1000.0,
        heatpump_code="LWC",
        operating_mode="heating",
        compressor_hz=40.0,
        compressor_runtime_s=0.0,
        compressor_total_s=0.0,
        compressor_running=False,
        bivalence_stage="one compressor allowed to run",
        backup_heater_runtime_s=0.0,
        backup_heater_total_s=0.0,
        backup_heater_running=False,
        status_line="heatpump idle",
        heat_heating_kwh=10.0,
        heat_dhw_kwh=5.0,
        heat_pool_kwh=0.0,
    )
    fields.update(kwargs)
    return Snapshot(**fields)


def test_behavior_summarizes_a_short_cycle():
    session = memory_session()
    start = utcnow() - timedelta(minutes=10)
    add_sample(session, snap(start, compressor_running=False, compressor_runtime_s=0))
    add_sample(session, snap(start + timedelta(minutes=1), compressor_running=True, compressor_runtime_s=30, flow_temp=36))
    add_sample(session, snap(start + timedelta(minutes=2), compressor_running=False, compressor_runtime_s=0))
    add_indoor(session, "living room", 21.5, start)
    session.flush()

    result = behavior_report(session, hours=24)
    assert result["compressor_starts"] == 1
    assert result["short_cycles"] == 1
    assert result["cycle_lengths_s"] == [30]
    assert result["latest_indoor_c"] == 21.5
    assert "cycle_length_summary" not in result


def test_behavior_replaces_a_long_cycle_list_with_a_summary(monkeypatch):
    monkeypatch.setattr("app.ai_advisor.CYCLE_LENGTH_LIMIT", 1)
    assert CYCLE_LENGTH_LIMIT > 1
    session = memory_session()
    moment = utcnow() - timedelta(minutes=20)
    for _ in range(3):
        add_sample(session, snap(moment, compressor_running=True, compressor_runtime_s=30))
        moment += timedelta(minutes=1)
        add_sample(session, snap(moment, compressor_running=False, compressor_runtime_s=0))
        moment += timedelta(minutes=1)
    session.flush()

    result = behavior_report(session, hours=24)
    assert "cycle_lengths_s" not in result
    assert result["cycle_length_summary"]["count"] == 3
    assert result["short_cycles"] == 3


def test_empty_window_is_an_error():
    session = memory_session()
    with pytest.raises(AgentDataError, match="No telemetry"):
        behavior_report(session, hours=1)


def test_energy_uses_the_stored_meter():
    session = memory_session()
    start = utcnow() - timedelta(hours=2)
    add_sample(session, snap(start, heat_heating_kwh=10))
    add_sample(session, snap(start + timedelta(hours=1), heat_heating_kwh=12))
    session.flush()
    result = energy_summary(session, hours=24)
    heating = result["period"]["channels"][0]
    assert heating["id"] == "heating"
    assert heating["kwh"] == 2.0


def test_status_includes_the_latest_sample():
    session = memory_session()
    add_sample(session, snap(utcnow() - timedelta(seconds=30), flow_temp=33.2))
    session.flush()
    result = pump_status_report(session)
    assert result["latest"]["flow_temp"] == 33.2
    assert result["latest"]["mode_text"]
    assert result["latest_age_s"] < 120


def test_demo_mode_does_not_read_the_controller(monkeypatch):
    monkeypatch.setattr("app.agent_data.get_settings", lambda: SimpleNamespace(demo_mode=True))

    def fail_read(*_args, **_kwargs):
        raise AssertionError("controller queried")

    monkeypatch.setattr("app.agent_data.read_settings", fail_read)
    result = household_settings_report(memory_session())
    assert result["live"] is False
    assert "demo mode" in result["detail"]
    assert {item["id"] for item in result["settings"]} == set(CURRENT)


def test_check_changes_keeps_a_legal_value_and_explains_the_rest():
    proposed = [
        {"id": "ID_Einst_BWS_akt", "value": 48, "reason": "Hot water is cool."},
        {"id": "ID_Einst_WK_akt", "value": 23, "reason": "Three degrees."},
        {"id": "ID_Ba_Hz_akt", "value": "Second heatsource", "reason": "Use the backup."},
        {"id": "ID_Ba_Bw_akt", "value": "Automatic", "reason": "Leave it."},
        {"id": "nope", "value": 1, "reason": "Unknown."},
    ]
    result = classify_changes(proposed, CURRENT)
    assert result["written"] is False
    assert result["kept"] == filter_changes(proposed, CURRENT)
    assert result["kept"] == [{"id": "ID_Einst_BWS_akt", "value": 48.0, "reason": "Hot water is cool."}]
    reasons = {item["id"]: item["reason"] for item in result["dropped"]}
    assert "at most 2" in reasons["ID_Einst_WK_akt"]
    assert reasons["ID_Ba_Hz_akt"] == "Second heatsource cannot be suggested."
    assert reasons["ID_Ba_Bw_akt"] == "Already set to this value."
    assert "Unknown setting" in reasons["nope"]
    too_hot = classify_changes([{"id": "ID_Einst_BWS_akt", "value": 60, "reason": "Too hot."}], CURRENT)
    assert too_hot["kept"] == []
    assert "at most 55" in too_hot["dropped"][0]["reason"]


def test_check_changes_uses_live_values(monkeypatch):
    poll_state.set_polling(True)
    monkeypatch.setattr("app.agent_data.get_settings", lambda: SimpleNamespace(demo_mode=False))
    monkeypatch.setattr("app.agent_data.controller_endpoint", lambda _session: ("127.0.0.1", 8888))
    monkeypatch.setattr(
        "app.agent_data.read_settings",
        lambda _host, _port: [{"id": setting_id, "value": value} for setting_id, value in CURRENT.items()],
    )
    result = check_changes_report(
        memory_session(),
        [{"id": "ID_Einst_WK_akt", "value": 21, "reason": "One degree."}],
    )
    assert result["kept"] == [{"id": "ID_Einst_WK_akt", "value": 21.0, "reason": "One degree."}]
    assert result["written"] is False


def test_tools_cannot_write():
    names = [tool.name for tool in mcp._tool_manager.list_tools()]
    assert names == ["pump_status", "behavior", "energy", "household_settings", "check_changes"]
    for name in names:
        assert "apply" not in name
        assert "write" not in name
    import app.agent_data as agent_data
    import app.mcp_server as mcp_server

    assert "write_setting" not in inspect.getsource(agent_data)
    assert "write_setting" not in inspect.getsource(mcp_server)
    assert [prompt.name for prompt in mcp._prompt_manager.list_prompts()] == ["review_pump"]


def test_behavior_tool_returns_a_window_error(monkeypatch):
    def fail(**_kwargs):
        raise AgentDataError("No telemetry in the selected window yet.")

    monkeypatch.setattr("app.mcp_server.load_behavior", fail)
    result = mcp._tool_manager.get_tool("behavior").fn()
    assert result == {"error": "No telemetry in the selected window yet."}


def test_mcp_is_mounted_on_the_logger():
    from app.main import app

    assert any(getattr(route, "path", None) == "/mcp" for route in app.routes)
