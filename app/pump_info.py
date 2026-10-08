"""The controller information page, grouped the way its own web screen groups it.

A row is included when its visibility flag is on. A flag of 0 hides the row.
Flags that were not returned stay hidden too. Panels with no flag (system,
error memory, switch-offs, and the four household settings) are always listed.
"""

from datetime import datetime

from app.fault_codes import fault_name
from app.settings_catalog import SETTINGS, present

_DASH = "—"


class _Row:
    def __init__(self, id, label, kind, source="calculations", visibility=None):
        self.id = id
        self.label = label
        self.kind = kind
        self.source = source
        self.visibility = visibility


def _temperature(id, label, visibility):
    return _Row(id, label, "celsius", visibility=visibility)


TEMPERATURES = (
    _temperature("ID_WEB_Temperatur_TVL", "Flow", "ID_Visi_Temp_Vorlauf"),
    _temperature("ID_WEB_Temperatur_TRL", "Return", "ID_Visi_Temp_Rucklauf"),
    _temperature("ID_WEB_Sollwert_TRL_HZ", "Return target", "ID_Visi_Temp_RL_Soll"),
    _temperature("ID_WEB_Temperatur_THG", "Hot gas", "ID_Visi_Temp_Heissgas"),
    _temperature("ID_WEB_Temperatur_TA", "Outdoor", "ID_Visi_Temp_Aussent"),
    _temperature("ID_WEB_Mitteltemperatur", "Outdoor 1 h", "ID_Visi_Mitteltemperatur"),
    _temperature("ID_WEB_Temperatur_TBW", "Hot water", "ID_Visi_Temp_BW_Ist"),
    _temperature("ID_WEB_Einst_BWS_akt", "Hot water target", "ID_Visi_Temp_BW_Soll"),
    _temperature("ID_WEB_Temperatur_TWA", "Heat source inlet", "ID_Visi_Temp_WQ_Ein"),
    _Row("ID_Einst_TVLmax_akt", "Max. flow", "tenth", "parameters", "ID_Visi_EinstTemp_Vorlaufmax"),
    _temperature("ID_WEB_LIN_ANSAUG_VERDAMPFER", "Suction evaporator", "ID_Visi_LIN_ANSAUG_VERDAMPFER"),
    _temperature("ID_WEB_LIN_ANSAUG_VERDICHTER", "Suction compressor", "ID_Visi_LIN_ANSAUG_VERDICHTER"),
    _temperature("ID_WEB_LIN_VDH", "Compressor heating", "ID_Visi_LIN_VDH"),
    _Row("ID_WEB_LIN_UH", "Superheat", "kelvin", visibility="ID_Visi_LIN_UH"),
    _Row("ID_WEB_LIN_UH_Soll", "Target superheat", "kelvin", visibility="ID_Visi_LIN_UH"),
)

INPUTS = (
    _Row("ID_WEB_ASDin", "ASD", "bool", visibility="ID_Visi_IN_ASD"),
    _Row("ID_WEB_BWTin", "BWT", "bool", visibility="ID_Visi_IN_BWT"),
    _Row("ID_WEB_EVUin", "EVU", "bool", visibility="ID_Visi_IN_EVU"),
    _Row("ID_WEB_HDin", "HD", "bool", visibility="ID_Visi_IN_HD"),
    _Row("ID_WEB_MOTin", "MOT", "bool", visibility="ID_Visi_IN_MOT"),
    _Row("ID_WEB_NDin", "ND", "bool", visibility="ID_Visi_IN_ND"),
    _Row("ID_WEB_PEXin", "PEX", "bool", visibility="ID_Visi_IN_PEX"),
    _Row("ID_WEB_SWTin", "SWT", "bool", visibility="ID_Visi_IN_SWT"),
    _Row("ID_WEB_SAXin", "SAX", "bool", visibility="ID_Visi_IN_SAX"),
    _Row("ID_WEB_SPLin", "SPL", "bool", visibility="ID_Visi_IN_SPL"),
    _Row("ID_WEB_LIN_HD", "High pressure", "bar", visibility="ID_Visi_LIN_Druck"),
    _Row("ID_WEB_LIN_ND", "Low pressure", "bar", visibility="ID_Visi_LIN_Druck"),
)

OUTPUTS = (
    _Row("ID_WEB_AVout", "Defrost valve", "bool", visibility="ID_Visi_OUT_Abtauventil"),
    _Row("ID_WEB_BUPout", "DHW pump", "bool", visibility="ID_Visi_OUT_BUP"),
    _Row("ID_WEB_HUPout", "Heating pump", "bool", visibility="ID_Visi_OUT_HUP"),
    _Row("ID_WEB_MA1out", "Mixer 1 open", "bool", visibility="ID_Visi_OUT_Mischer1Auf"),
    _Row("ID_WEB_MZ1out", "Mixer 1 close", "bool", visibility="ID_Visi_OUT_Mischer1Zu"),
    _Row("ID_WEB_VENout", "Ventilation", "bool", visibility="ID_Visi_OUT_Ventilation"),
    _Row("ID_WEB_VBOout", "VBO", "bool", visibility="ID_Visi_OUT_Ventil_BOSUP"),
    _Row("ID_WEB_VD1out", "Compressor", "bool", visibility="ID_Visi_OUT_Verdichter1"),
    _Row("ID_WEB_VD2out", "Compressor 2", "bool", visibility="ID_Visi_OUT_Verdichter2"),
    _Row("ID_WEB_ZIPout", "ZIP", "bool", visibility="ID_Visi_OUT_ZIP"),
    _Row("ID_WEB_ZUPout", "ZUP", "bool", visibility="ID_Visi_OUT_ZUP"),
    _Row("ID_WEB_ZW1out", "ZWE1", "bool", visibility="ID_Visi_OUT_ZWE1"),
    _Row("ID_WEB_ZW2SSTout", "ZWE2-SST", "bool", visibility="ID_Visi_OUT_ZWE2_SST"),
    _Row("ID_WEB_ZW3SSTout", "ZWE3", "bool", visibility="ID_Visi_OUT_ZWE3"),
    _Row("ID_WEB_FP2out", "Floor pump 2", "bool", visibility="ID_Visi_OUT_FUP2"),
    _Row("ID_WEB_SLPout", "Solar pump", "bool", visibility="ID_Visi_OUT_SLP"),
    _Row("ID_WEB_SUPout", "Pool pump", "bool", visibility="ID_Visi_OUT_SUP"),
    _Row("ID_WEB_MZ2out", "Mixer 2 close", "bool", visibility="ID_Visi_OUT_Mischer2Zu"),
    _Row("ID_WEB_MA2out", "Mixer 2 open", "bool", visibility="ID_Visi_OUT_Mischer2Auf"),
    _Row("ID_WEB_MZ3out", "Mixer 3 close", "bool", visibility="ID_Visi_OUT_Mischer3Zu"),
    _Row("ID_WEB_MA3out", "Mixer 3 open", "bool", visibility="ID_Visi_OUT_Mischer3Auf"),
    _Row("ID_WEB_FP3out", "Floor pump 3", "bool", visibility="ID_Visi_OUT_FUP3"),
    _Row("ID_WEB_LIN_VDH_out", "Compressor heating", "bool", visibility="ID_Visi_LIN_VDH"),
)

ELAPSED = (
    _Row("ID_WEB_Time_WPein_akt", "Heat pump since", "duration", visibility="ID_Visi_AblaufZ_WP_Seit"),
    _Row("ID_WEB_Time_ZWE1_akt", "ZWE1 since", "duration", visibility="ID_Visi_AblaufZ_ZWE1_seit"),
    _Row("ID_WEB_Time_ZWE2_akt", "ZWE2 since", "duration", visibility="ID_Visi_AblaufZ_ZWE2_seit"),
    _Row("ID_WEB_Timer_EinschVerz", "Mains lockout", "duration", visibility="ID_Visi_AblaufZ_Netzeinv"),
    _Row("ID_WEB_Time_SSPAUS_akt", "Cycle lock", "duration", visibility="ID_Visi_AblaufZ_SSP_Zeit1"),
    _Row("ID_WEB_Time_VDStd_akt", "Compressor off since", "duration", visibility="ID_Visi_AblaufZ_VD_Stand"),
    _Row("ID_WEB_Time_HRM_akt", "Heating extra time", "duration", visibility="ID_Visi_AblaufZ_HRM_Zeit"),
    _Row("ID_WEB_Time_HRW_akt", "Heating max time", "duration", visibility="ID_Visi_AblaufZ_HRW_Zeit"),
    _Row("ID_WEB_Time_LGS_akt", "Thermal disinfection", "duration", visibility="ID_Visi_AblaufZ_TDI_seit"),
    _Row("ID_WEB_Time_SBW_akt", "Hot water lockout", "duration", visibility="ID_Visi_AblaufZ_Sperre_BW"),
)

HOURS = (
    _Row("ID_WEB_Zaehler_BetrZeitVD1", "Compressor hours", "hours", visibility="ID_Visi_Bst_BStdVD1"),
    _Row("ID_WEB_Zaehler_BetrZeitImpVD1", "Compressor starts", "count", visibility="ID_Visi_Bst_ImpVD1"),
    _Row("ID_WEB_Zaehler_BetrZeitVD2", "Compressor 2 hours", "hours", visibility="ID_Visi_Bst_BStdVD2"),
    _Row("ID_WEB_Zaehler_BetrZeitImpVD2", "Compressor 2 starts", "count", visibility="ID_Visi_Bst_ImpVD2"),
    _Row("ID_WEB_Zaehler_BetrZeitZWE1", "ZWE1 hours", "hours", visibility="ID_Visi_Bst_BStdZWE1"),
    _Row("ID_WEB_Zaehler_BetrZeitZWE2", "ZWE2 hours", "hours", visibility="ID_Visi_Bst_BStdZWE2"),
    _Row("ID_WEB_Zaehler_BetrZeitZWE3", "ZWE3 hours", "hours", visibility="ID_Visi_Bst_BStdZWE3"),
    _Row("ID_WEB_Zaehler_BetrZeitWP", "Heat pump hours", "hours", visibility="ID_Visi_Bst_BStdWP"),
    _Row("ID_WEB_Zaehler_BetrZeitHz", "Heating hours", "hours", visibility="ID_Visi_Bst_BStdHz"),
    _Row("ID_WEB_Zaehler_BetrZeitBW", "Hot water hours", "hours", visibility="ID_Visi_Bst_BStdBW"),
    _Row("ID_WEB_Zaehler_BetrZeitKue", "Cooling hours", "hours", visibility="ID_Visi_Bst_BStdKue"),
)

SYSTEM = (
    _Row("ID_WEB_Code_WP_akt", "Heat pump type", "text"),
    _Row("ID_WEB_SoftStand", "Software", "text"),
    _Row("ID_WEB_BIV_Stufe_akt", "Bivalence", "text"),
    _Row("ID_WEB_WP_BZ_akt", "Operating mode", "text"),
)

HEAT = (
    ("ID_WEB_WMZ_Heizung", "Heating"),
    ("ID_WEB_WMZ_Brauchwasser", "Hot water"),
    ("ID_WEB_WMZ_Schwimmbad", "Pool"),
)


def build_sections(pump) -> list[dict]:
    """Group one live read into the information-page panels."""
    sections = [_settings_section(pump)]
    _append(sections, "system", "System", _rows(pump, SYSTEM))
    _append(sections, "errors", "Error memory", _events(pump, "ID_WEB_ERROR_Time", "ID_WEB_ERROR_Nr", "error"))
    _append(sections, "temperatures", "Temperatures", _rows(pump, TEMPERATURES))
    _append(sections, "inputs", "Inputs", _rows(pump, INPUTS))
    _append(sections, "outputs", "Outputs", _rows(pump, OUTPUTS))
    _append(sections, "elapsed", "Elapsed time", _rows(pump, ELAPSED))
    _append(sections, "hours", "Operating hours", _rows(pump, HOURS))
    _append(sections, "switchoffs", "Switch-offs", _events(pump, "ID_WEB_Switchoff_file_Time", "ID_WEB_Switchoff_file_Nr", "switchoff"))
    _append(sections, "heat", "Heat quantity", _heat(pump))
    return sections


def sections_from_sample(sample: dict | None) -> list[dict]:
    """Fill the panels a stored sample can answer. The rest stay hidden."""
    if not sample:
        return []
    sections = []
    _append(sections, "temperatures", "Temperatures", _sample_rows(sample, (
        ("flow_temp", "ID_WEB_Temperatur_TVL", "Flow", "celsius"),
        ("return_temp", "ID_WEB_Temperatur_TRL", "Return", "celsius"),
        ("return_setpoint", "ID_WEB_Sollwert_TRL_HZ", "Return target", "celsius"),
        ("outdoor_temp", "ID_WEB_Temperatur_TA", "Outdoor", "celsius"),
        ("dhw_temp", "ID_WEB_Temperatur_TBW", "Hot water", "celsius"),
        ("dhw_setpoint", "ID_WEB_Einst_BWS_akt", "Hot water target", "celsius"),
    )))
    _append(sections, "outputs", "Outputs", _sample_rows(sample, (
        ("compressor_running", "ID_WEB_VD1out", "Compressor", "bool"),
        ("backup_heater_running", "ID_WEB_ZW1out", "ZWE1", "bool"),
    )))
    _append(sections, "elapsed", "Elapsed time", _sample_rows(sample, (
        ("compressor_runtime_s", "ID_WEB_Time_WPein_akt", "Heat pump since", "duration"),
        ("backup_heater_runtime_s", "ID_WEB_Time_ZWE1_akt", "ZWE1 since", "duration"),
    )))
    _append(sections, "hours", "Operating hours", _sample_rows(sample, (
        ("compressor_total_s", "ID_WEB_Zaehler_BetrZeitVD1", "Compressor hours", "hours"),
        ("backup_heater_total_s", "ID_WEB_Zaehler_BetrZeitZWE1", "ZWE1 hours", "hours"),
    )))
    _append(sections, "system", "System", _sample_rows(sample, (
        ("heatpump_code", "ID_WEB_Code_WP_akt", "Heat pump type", "text"),
        ("bivalence_stage", "ID_WEB_BIV_Stufe_akt", "Bivalence", "text"),
        ("operating_mode", "ID_WEB_WP_BZ_akt", "Operating mode", "text"),
    )))
    _append(sections, "heat", "Heat quantity", _sample_heat(sample))
    return sections


def _settings_section(pump) -> dict:
    rows = []
    for spec in SETTINGS:
        rows.append(present(spec, _setting_value(spec, _value(pump, "parameters", spec.id))))
    return {"id": "settings", "title": "Settings", "rows": rows}


def _setting_value(spec, raw):
    if raw is None:
        return None
    if spec.kind == "choice":
        text = str(raw).strip()
        return text or None
    try:
        return round(float(raw), 1)
    except (TypeError, ValueError):
        return None


def _rows(pump, specs) -> list[dict]:
    rows = []
    for spec in specs:
        if not _shown(pump, spec.visibility):
            continue
        rows.append({
            "id": spec.id,
            "label": spec.label,
            "display": _format(spec.kind, _value(pump, spec.source, spec.id)),
        })
    return rows


def _sample_rows(sample, fields) -> list[dict]:
    rows = []
    for key, row_id, label, kind in fields:
        if sample.get(key) is None:
            continue
        rows.append({"id": row_id, "label": label, "display": _format(kind, sample[key])})
    return rows


def _heat(pump) -> list[dict]:
    if not _shown(pump, "ID_Visi_Waermemenge_WS"):
        return []
    return _heat_rows(
        _value(pump, "calculations", row_id) for row_id, _label in HEAT
    )


def _sample_heat(sample) -> list[dict]:
    values = [sample.get("heat_heating_kwh"), sample.get("heat_dhw_kwh"), sample.get("heat_pool_kwh")]
    if all(value is None for value in values):
        return []
    rows = []
    numbers = []
    for (row_id, label), raw in zip(HEAT, values):
        if raw is None:
            continue
        numbers.append(float(raw))
        rows.append({"id": row_id, "label": label, "display": _format("energy", raw)})
    rows.append({"id": "heat-total", "label": "Total", "display": _format("energy", sum(numbers))})
    return rows


def _heat_rows(values) -> list[dict]:
    numbers = []
    rows = []
    for (row_id, label), raw in zip(HEAT, values):
        if _number(raw) is not None:
            numbers.append(_number(raw))
        rows.append({"id": row_id, "label": label, "display": _format("energy", raw)})
    total = None if not numbers else sum(numbers)
    rows.append({"id": "heat-total", "label": "Total", "display": _format("energy", total)})
    return rows


def _events(pump, time_prefix, code_prefix, kind) -> list[dict]:
    rows = []
    for index in range(5):
        when = _stamp(_value(pump, "calculations", f"{time_prefix}{index}"))
        raw = _value(pump, "calculations", f"{code_prefix}{index}")
        if kind == "error":
            row = _error_row(index, when, raw)
            if row is not None:
                rows.append(row)
            continue
        reason = _reason(raw)
        if when is None and reason is None:
            continue
        rows.append({
            "id": f"{kind}-{index}",
            "label": when or _DASH,
            "display": reason or _DASH,
        })
    return rows


def _error_row(index, when, raw):
    number = _error_code(raw)
    if when is None and number is None:
        return None
    name = fault_name(number) if number is not None else None
    code = _DASH if number is None else str(number)
    display = f"{code} · {name}" if name else code
    return {
        "id": f"error-{index}",
        "label": when or _DASH,
        "display": display,
        "time": when or _DASH,
        "code": code,
        "name": name or _DASH,
    }


def _reason(value):
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _error_code(value):
    if value in (None, False, ""):
        return None
    number = _number(value)
    if number is None or number == 0:
        return None
    if not number.is_integer():
        return None
    return int(number)


def _shown(pump, visibility) -> bool:
    if not visibility:
        return True
    value = _value(pump, "visibilities", visibility)
    return value == 1 or value is True


def _value(pump, source, name):
    bag = getattr(pump, source, None)
    if bag is None:
        return None
    field = bag.get(name)
    if field is None:
        return None
    return getattr(field, "value", None)


def _append(sections, section_id, title, rows) -> None:
    if rows:
        sections.append({"id": section_id, "title": title, "rows": rows})


def _format(kind, value) -> str:
    if kind == "bool":
        if value is None:
            return _DASH
        return "On" if bool(value) else "Off"
    if kind == "text":
        if value is None:
            return _DASH
        text = str(value).strip()
        return text or _DASH
    if kind == "tenth":
        number = _number(value)
        if number is None:
            return _DASH
        return _measure(number / 10, 1, "°C")
    number = _number(value)
    if number is None:
        return _DASH
    if kind == "celsius":
        return _measure(number, 1, "°C")
    if kind == "kelvin":
        return _measure(number, 1, "K")
    if kind == "bar":
        return _measure(number, 2, "bar")
    if kind == "energy":
        return _measure(number, 1, "kWh")
    if kind == "duration":
        return _duration(number)
    if kind == "hours":
        return f"{int(number // 3600)} h"
    if kind == "count":
        return str(int(number))
    return _DASH


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _measure(value, digits, unit) -> str:
    return f"{_european(value, digits)} {unit}"


def _european(value, digits) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def _duration(seconds) -> str:
    total = int(round(seconds))
    if total < 0:
        total = 0
    hours, rest = divmod(total, 3600)
    minutes = int(round(rest / 60))
    if minutes == 60:
        hours += 1
        minutes = 0
    if hours <= 0:
        return f"{minutes} min"
    return f"{hours} h {minutes} min"


def _stamp(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value <= 0:
            return None
        value = datetime.fromtimestamp(value)
    if not isinstance(value, datetime):
        return None
    if value.year < 2000:
        return None
    return value.strftime("%d.%m.%Y %H:%M")
