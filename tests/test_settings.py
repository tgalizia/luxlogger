"""Allowlist checks. These tests do not open a socket."""

import pytest

from app.ai_advisor import suggest_settings
from app.luxtronik_client import SettingsWriteError, commit_setting
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
