"""Information-page grouping. These tests do not open a socket."""

from datetime import datetime

from app.pump_info import build_sections, sections_from_sample


class _Field:
    def __init__(self, value):
        self.value = value


class _Bag:
    def __init__(self, values):
        self._values = values

    def get(self, name):
        if name not in self._values:
            return None
        return _Field(self._values[name])


class _Pump:
    def __init__(self, calculations=None, parameters=None, visibilities=None):
        self.calculations = _Bag(calculations or {})
        self.parameters = _Bag(parameters or {})
        self.visibilities = _Bag(visibilities or {})


def _sections(pump):
    return {item["id"]: item for item in build_sections(pump)}


def _rows(section):
    return {row["label"]: row["display"] for row in section["rows"]}


def test_hidden_temperature_is_omitted_and_visible_ones_scale():
    pump = _Pump(
        calculations={"ID_WEB_Temperatur_TVL": 21.9, "ID_WEB_Temperatur_TRL": 18.5},
        parameters={"ID_Einst_TVLmax_akt": 750},
        visibilities={
            "ID_Visi_Temp_Vorlauf": 1,
            "ID_Visi_Temp_Rucklauf": 0,
            "ID_Visi_EinstTemp_Vorlaufmax": 1,
        },
    )
    rows = _rows(_sections(pump)["temperatures"])
    assert rows["Flow"] == "21,9 °C"
    assert rows["Max. flow"] == "75,0 °C"
    assert "Return" not in rows


def test_visible_output_that_is_off_stays_on_the_page():
    pump = _Pump(
        calculations={"ID_WEB_VD1out": False, "ID_WEB_HUPout": True},
        visibilities={"ID_Visi_OUT_Verdichter1": 1, "ID_Visi_OUT_HUP": 0},
    )
    rows = _rows(_sections(pump)["outputs"])
    assert rows == {"Compressor": "Off"}


def test_hours_and_heat_use_the_controller_units():
    pump = _Pump(
        calculations={
            "ID_WEB_Zaehler_BetrZeitVD1": 50788 * 3600,
            "ID_WEB_Time_WPein_akt": 65,
            "ID_WEB_WMZ_Heizung": 10.0,
            "ID_WEB_WMZ_Brauchwasser": 2.5,
            "ID_WEB_WMZ_Schwimmbad": 0.0,
        },
        visibilities={
            "ID_Visi_Bst_BStdVD1": 1,
            "ID_Visi_AblaufZ_WP_Seit": 1,
            "ID_Visi_Waermemenge_WS": 1,
        },
    )
    sections = _sections(pump)
    assert _rows(sections["hours"])["Compressor hours"] == "50788 h"
    assert _rows(sections["elapsed"])["Heat pump since"] == "1 min"
    heat = _rows(sections["heat"])
    assert heat["Heating"] == "10,0 kWh"
    assert heat["Pool"] == "0,0 kWh"
    assert heat["Total"] == "12,5 kWh"


def test_heat_meter_hides_when_the_controller_hides_it():
    pump = _Pump(
        calculations={"ID_WEB_WMZ_Heizung": 10.0},
        visibilities={"ID_Visi_Waermemenge_WS": 0},
    )
    assert "heat" not in _sections(pump)


def test_empty_error_slot_is_hidden_and_a_switch_off_is_kept():
    pump = _Pump(
        calculations={
            "ID_WEB_ERROR_Nr0": 0,
            "ID_WEB_ERROR_Time0": datetime(1970, 1, 1),
            "ID_WEB_Switchoff_file_Nr0": "no request",
            "ID_WEB_Switchoff_file_Time0": datetime(2026, 8, 8, 11, 23),
        }
    )
    sections = _sections(pump)
    assert "errors" not in sections
    switch = sections["switchoffs"]["rows"][0]
    assert switch["label"] == "08.08.2026 11:23"
    assert switch["display"] == "no request"


def test_known_error_includes_its_name_and_an_unknown_code_stays_a_number():
    pump = _Pump(
        calculations={
            "ID_WEB_ERROR_Nr0": 718,
            "ID_WEB_ERROR_Time0": datetime(2026, 8, 8, 11, 23),
            "ID_WEB_ERROR_Nr1": 999,
            "ID_WEB_ERROR_Time1": datetime(2026, 8, 4, 11, 54),
        }
    )
    sections = build_sections(pump)
    rows = {item["id"]: item for item in sections}["errors"]["rows"]
    assert rows[0]["display"] == "718 · Max. outdoor temp."
    assert rows[0]["time"] == "08.08.2026 11:23"
    assert rows[0]["code"] == "718"
    assert rows[0]["name"] == "Max. outdoor temp."
    assert rows[1]["display"] == "999"
    assert rows[1]["name"] == "—"
    ids = [item["id"] for item in sections]
    assert ids.index("system") == ids.index("settings") + 1
    assert ids.index("errors") == ids.index("system") + 1


def test_settings_use_the_household_allowlist():
    pump = _Pump(
        parameters={"ID_Ba_Hz_akt": "Second heatsource", "ID_Einst_BWS_akt": 46.0},
    )
    rows = {row["id"]: row for row in _sections(pump)["settings"]["rows"]}
    assert rows["ID_Ba_Hz_akt"]["display"] == "Additional heat generator"
    assert rows["ID_Ba_Hz_akt"]["kind"] == "choice"
    assert rows["ID_Einst_BWS_akt"]["display"] == "46,0 °C"
    assert rows["ID_Einst_WK_akt"]["display"] == "—"
    assert len(rows) == 4


def test_demo_sample_fills_only_the_stored_rows():
    sections = {item["id"]: item for item in sections_from_sample({
        "flow_temp": 21.9,
        "operating_mode": "heating",
        "compressor_running": False,
        "heat_heating_kwh": 10.0,
        "heat_dhw_kwh": None,
        "heat_pool_kwh": 0.0,
    })}
    assert "settings" not in sections
    assert "inputs" not in sections
    assert _rows(sections["temperatures"]) == {"Flow": "21,9 °C"}
    assert _rows(sections["outputs"]) == {"Compressor": "Off"}
    assert _rows(sections["system"]) == {"Operating mode": "heating"}
    heat = _rows(sections["heat"])
    assert "Hot water" not in heat
    assert heat["Pool"] == "0,0 kWh"
    assert heat["Total"] == "10,0 kWh"
