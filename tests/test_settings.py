"""Allowlist checks. These tests do not open a socket."""

import pytest

from datetime import timedelta

from fastapi import HTTPException

from app.ai_advisor import (
    SETTINGS_PROMPT,
    SYSTEM_PROMPT,
    AdvisorError,
    _diagnostics_prompt,
    context_block,
    limit_findings,
    suggest_settings,
    validate_model,
    validate_provider,
    with_context,
)
from app.database import utcnow
from app.main import _advice_window
from app.luxtronik_client import SettingsWriteError, commit_setting
from app.runtime import PreferenceError, validate_port
from app.settings_catalog import SettingsError, filter_changes, validate_value


CURRENT = {
    "ID_Ba_Hz_akt": "Automatic",
    "ID_Ba_Bw_akt": "Automatic",
    "ID_Einst_BWS_akt": 46.0,
    "ID_Einst_WK_akt": 20.0,
}


def test_unknown_id_is_rejected():
    with pytest.raises(SettingsError):
        validate_value("ID_Einst_HzHwHKE_akt", 1.2)


def test_hot_water_above_55_is_rejected():
    with pytest.raises(SettingsError):
        validate_value("ID_Einst_BWS_akt", 56)


def test_additional_heat_generator_is_allowed():
    assert validate_value("ID_Ba_Hz_akt", "Additional heat generator") == "Second heatsource"
    assert validate_value("ID_Ba_Bw_akt", "Second heatsource") == "Second heatsource"


def test_empty_suggestion_leaves_every_setting_untouched():
    current = [
        {"id": "ID_Ba_Hz_akt", "value": "Automatic"},
        {"id": "ID_Ba_Bw_akt", "value": "Automatic"},
        {"id": "ID_Einst_BWS_akt", "value": 46.0},
        {"id": "ID_Einst_WK_akt", "value": 20.0},
    ]
    before = [dict(item) for item in current]
    accepted = suggest_settings(current, {"window_hours": 24}, complete=lambda _prompt: '{"changes": []}')
    assert accepted == []
    assert current == before
    assert filter_changes([], CURRENT) == []


def test_context_includes_known_equipment_and_note():
    block = context_block(
        {
            "pump_maker": "Alpha Innotec",
            "pump_model": "LWC",
            "controller_model": "",
            "controller_software": "V1.88",
        },
        "The house is cold in the morning.",
    )
    assert "Pump maker: Alpha Innotec" in block
    assert "Pump model: LWC" in block
    assert "Controller software: V1.88" in block
    assert "Controller:" not in block
    assert "Owner note:\nThe house is cold in the morning." in block


def test_blank_equipment_and_empty_note_are_omitted():
    assert context_block({"pump_maker": "  ", "controller_model": ""}, "  ") == ""
    assert context_block({"pump_model": "LD7"}, None) == "Equipment:\nPump model: LD7"


def test_note_reaches_the_settings_prompt():
    seen = {}

    def complete(prompt):
        seen["prompt"] = prompt
        return '{"changes": []}'

    current = [
        {"id": "ID_Ba_Hz_akt", "value": "Automatic"},
        {"id": "ID_Ba_Bw_akt", "value": "Automatic"},
        {"id": "ID_Einst_BWS_akt", "value": 46.0},
        {"id": "ID_Einst_WK_akt", "value": 20.0},
    ]
    accepted = suggest_settings(
        current,
        {"window_hours": 24},
        complete=complete,
        identity={"pump_maker": "Novelan"},
        note="Too many starts",
    )
    assert accepted == []
    prompt = seen["prompt"]
    assert "Pump maker: Novelan" in prompt
    assert "Owner note:\nToo many starts" in prompt
    assert "Controller:" not in prompt
    assert prompt.index("Equipment:") < prompt.index("Owner note:") < prompt.index("Current settings JSON:")


def test_equipment_and_note_lead_the_user_message():
    prompt = with_context("Diagnostics JSON:\n{}", {"pump_model": "LD7"}, "Cold mornings")
    assert prompt.index("Equipment:") < prompt.index("Owner note:") < prompt.index("Diagnostics JSON:")


def test_prompts_use_equipment_and_answer_the_owner_note_first():
    for prompt in (SYSTEM_PROMPT, SETTINGS_PROMPT):
        assert "pump maker, pump model, controller, and controller software" in prompt
        assert "answer that goal or problem first" in prompt
        assert "Alpha Innotec" not in prompt
        assert "Luxtronik 2" not in prompt
    assert "you may change it to an allowed mode" in SETTINGS_PROMPT


def _current_settings():
    return [
        {"id": "ID_Ba_Hz_akt", "value": "Automatic"},
        {"id": "ID_Ba_Bw_akt", "value": "Automatic"},
        {"id": "ID_Einst_BWS_akt", "value": 46.0},
        {"id": "ID_Einst_WK_akt", "value": 20.0},
    ]


def test_cycle_lengths_at_the_cap_stay_unchanged():
    lengths = list(range(200))
    findings = {"cycle_lengths_s": lengths, "short_cycle_threshold_s": 600}
    assert limit_findings(findings) is findings
    prompt = _diagnostics_prompt(findings)
    assert "cycle_lengths_s" in prompt
    assert "cycle_length_summary" not in prompt


def test_cycle_lengths_over_the_cap_are_summarized():
    lengths = list(range(1, 202))
    findings = {"cycle_lengths_s": lengths, "sample_count": 500, "short_cycle_threshold_s": 600}
    limited = limit_findings(findings)
    assert "cycle_lengths_s" not in limited
    assert limited["sample_count"] == 500
    assert limited["cycle_length_summary"] == {
        "count": 201,
        "min_s": 1,
        "median_s": 101,
        "p90_s": 181,
        "max_s": 201,
    }
    assert findings["cycle_lengths_s"] == lengths
    prompt = _diagnostics_prompt(findings)
    assert "cycle_length_summary" in prompt
    assert "cycle_lengths_s" not in prompt


def test_setting_prompt_summarizes_a_long_cycle_list():
    seen = {}

    def complete(prompt):
        seen["prompt"] = prompt
        return '{"changes": []}'

    suggest_settings(
        _current_settings(),
        {"cycle_lengths_s": list(range(1, 202)), "short_cycles": 40, "completed_cycles": 201},
        complete=complete,
    )
    assert "cycle_length_summary" in seen["prompt"]
    assert "cycle_lengths_s" not in seen["prompt"]
    assert '"short_cycles": 40' in seen["prompt"]


def test_advice_window_defaults_to_one_day_and_rejects_an_old_start():
    start, end, window = _advice_window(None, None, None, 24)
    assert end is None
    assert window == 24
    assert abs((utcnow() - start).total_seconds() - 24 * 3600) < 5

    start_at = utcnow() - timedelta(days=3, hours=2)
    end_at = utcnow() - timedelta(days=1)
    start, end, window = _advice_window(start_at, end_at, None, 24)
    assert start == start_at
    assert end == end_at
    assert window == 50

    with pytest.raises(HTTPException) as caught:
        _advice_window(utcnow() - timedelta(days=801), None, None, 24)
    assert caught.value.status_code == 400

    with pytest.raises(HTTPException) as caught:
        _advice_window(end_at, start_at, None, 24)
    assert caught.value.status_code == 400


def test_unknown_provider_and_model_are_rejected():
    with pytest.raises(AdvisorError):
        validate_provider("local")
    with pytest.raises(AdvisorError):
        validate_model("openai", "not-a-model")
    with pytest.raises(AdvisorError):
        validate_model("openai", "gemini-3.8-flash")
    assert validate_model("openai", "gpt-4o-mini") == "gpt-4o-mini"
    assert validate_provider(" Gemini ") == "gemini"


def test_port_must_be_in_range():
    assert validate_port("8889") == 8889
    with pytest.raises(PreferenceError):
        validate_port(0)
    with pytest.raises(PreferenceError):
        validate_port(70000)
    with pytest.raises(PreferenceError):
        validate_port("pump")


def test_invalid_suggestions_are_dropped():
    raw = [
        {"id": "ID_Einst_HzHwHKE_akt", "value": 1.2, "reason": "curve"},
        {"id": "ID_Einst_BWS_akt", "value": 60, "reason": "hotter"},
        {"id": "ID_Ba_Hz_akt", "value": "Second heatsource", "reason": "heater"},
        {"id": "ID_Einst_WK_akt", "value": 30, "reason": "too far"},
    ]
    assert filter_changes(raw, CURRENT) == []


class _Field:
    def __init__(self, value):
        self.value = value


class _Parameters:
    def __init__(self, values, accept=True):
        self.values = dict(values)
        self.queue = {}
        self.accept = accept
        self.writes = 0
        self.pending = None

    def get(self, name):
        if name not in self.values:
            return None
        return _Field(self.values[name])

    def set(self, name, value):
        if isinstance(value, str):
            self.queue[3] = 2
        else:
            self.queue[2] = int(round(float(value) * 10))
        self.pending = (name, value)


class _Pump:
    def __init__(self, parameters):
        self.parameters = parameters

    def write(self):
        self.parameters.writes += 1
        if self.parameters.accept and self.parameters.pending:
            name, value = self.parameters.pending
            self.parameters.values[name] = value
        self.parameters.queue = {}

    def read(self):
        return None


def test_rejected_values_do_not_write():
    pump = _Pump(_Parameters({"ID_Einst_BWS_akt": 46.0, "ID_Ba_Hz_akt": "Automatic"}))
    with pytest.raises(SettingsError):
        commit_setting(pump, "ID_Einst_BWS_akt", 60)
    with pytest.raises(SettingsError):
        commit_setting(pump, "ID_Ba_Hz_akt", "Turbo")
    with pytest.raises(SettingsError):
        commit_setting(pump, "not-a-setting", "Off")
    assert pump.parameters.writes == 0
    assert pump.parameters.values["ID_Einst_BWS_akt"] == 46.0


def test_readback_mismatch_is_not_success():
    pump = _Pump(_Parameters({"ID_Einst_BWS_akt": 46.0}, accept=False))
    with pytest.raises(SettingsWriteError):
        commit_setting(pump, "ID_Einst_BWS_akt", 45)
    assert pump.parameters.values["ID_Einst_BWS_akt"] == 46.0
