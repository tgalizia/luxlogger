"""Household settings this app is allowed to change."""

from dataclasses import dataclass


class SettingsError(Exception):
    """A setting id or value is outside the allowlist."""


@dataclass(frozen=True)
class SettingSpec:
    id: str
    label: str
    kind: str
    options: tuple[str, ...] | None = None
    minimum: float | None = None
    maximum: float | None = None
    max_delta: float | None = None
    unit: str = ""


SETTINGS: tuple[SettingSpec, ...] = (
    SettingSpec(
        id="ID_Ba_Hz_akt",
        label="Heating mode",
        kind="choice",
        options=("Automatic", "Additional heat generator", "Party", "Holidays", "Off"),
    ),
    SettingSpec(
        id="ID_Ba_Bw_akt",
        label="Hot water mode",
        kind="choice",
        options=("Automatic", "Additional heat generator", "Party", "Holidays", "Off"),
    ),
    SettingSpec(
        id="ID_Einst_BWS_akt",
        label="Hot water temperature",
        kind="number",
        minimum=40,
        maximum=55,
        unit="°C",
    ),
    SettingSpec(
        id="ID_Einst_WK_akt",
        label="Heating setpoint",
        kind="number",
        minimum=15,
        maximum=35,
        max_delta=2,
        unit="°C",
    ),
)

# The controller stores this mode as "Second heatsource". Its own screen abbreviates the name.
CHOICE_VALUES = {"Additional heat generator": "Second heatsource"}
CHOICE_LABELS = {value: label for label, value in CHOICE_VALUES.items()}

_BY_ID = {spec.id: spec for spec in SETTINGS}


def get_spec(setting_id: str) -> SettingSpec:
    spec = _BY_ID.get(setting_id)
    if spec is None:
        raise SettingsError(f"Unknown setting {setting_id}.")
    return spec


def validate_value(setting_id: str, value, current=None):
    """Return a canonical value, or raise SettingsError."""
    spec = get_spec(setting_id)
    if spec.kind == "choice":
        if not isinstance(value, str):
            raise SettingsError(f"{spec.label} cannot be set to {value!r}.")
        canonical = CHOICE_VALUES.get(value, value)
        allowed = {CHOICE_VALUES.get(option, option) for option in spec.options}
        if canonical not in allowed:
            raise SettingsError(f"{spec.label} cannot be set to {value!r}.")
        return canonical
    number = _number(spec, value)
    if spec.max_delta is not None:
        if current is None:
            raise SettingsError(f"{spec.label} needs the current value before it can change.")
        baseline = _number(spec, current)
        if abs(number - baseline) > spec.max_delta + 1e-6:
            raise SettingsError(
                f"{spec.label} can move by at most {_european(spec.max_delta)} °C from {_european(baseline)} °C."
            )
    return number


def values_match(setting_id: str, actual, expected) -> bool:
    spec = get_spec(setting_id)
    if actual is None or expected is None:
        return False
    if spec.kind == "choice":
        return _choice_value(str(actual)) == _choice_value(str(expected))
    return round(float(actual), 1) == round(float(expected), 1)


def format_value(setting_id: str, value) -> str:
    spec = get_spec(setting_id)
    if value is None:
        return "—"
    if spec.kind == "choice":
        text = str(value).strip()
        return CHOICE_LABELS.get(text, text)
    text = _european(float(value), 1)
    if spec.unit:
        return f"{text} {spec.unit}"
    return text


def present(spec: SettingSpec, value) -> dict:
    return {
        "id": spec.id,
        "label": spec.label,
        "kind": spec.kind,
        "unit": spec.unit,
        "options": None if spec.options is None else [_choice_value(option) for option in spec.options],
        "option_labels": None
        if spec.options is None
        else { _choice_value(option): CHOICE_LABELS.get(_choice_value(option), option) for option in spec.options },
        "minimum": spec.minimum,
        "maximum": spec.maximum,
        "max_delta": spec.max_delta,
        "value": value,
        "display": format_value(spec.id, value),
    }


def filter_changes(changes, current_by_id: dict) -> list[dict]:
    """Drop unknown ids, out-of-range values, and suggestions that match the current value."""
    if not isinstance(changes, list):
        return []
    kept = []
    seen = set()
    for item in changes:
        if not isinstance(item, dict):
            continue
        setting_id = item.get("id")
        if not isinstance(setting_id, str) or setting_id in seen:
            continue
        try:
            value = validate_value(setting_id, item.get("value"), current_by_id.get(setting_id))
        except SettingsError:
            continue
        if values_match(setting_id, current_by_id.get(setting_id), value):
            continue
        if value == "Second heatsource":
            continue
        reason = str(item.get("reason") or "").strip()[:400]
        kept.append({"id": setting_id, "value": value, "reason": reason})
        seen.add(setting_id)
    return kept


def _choice_value(value: str) -> str:
    text = value.strip()
    return CHOICE_VALUES.get(text, text)


def _european(value: float, digits: int | None = None) -> str:
    text = f"{value:g}" if digits is None else f"{value:.{digits}f}"
    return text.replace(".", ",")


def _number(spec: SettingSpec, value) -> float:
    if isinstance(value, bool) or isinstance(value, str) and not value.strip():
        raise SettingsError(f"{spec.label} needs a temperature.")
    try:
        number = round(float(value), 1)
    except (TypeError, ValueError):
        raise SettingsError(f"{spec.label} needs a temperature.") from None
    if spec.minimum is not None and number < spec.minimum:
        raise SettingsError(f"{spec.label} must be at least {_european(spec.minimum)} °C.")
    if spec.maximum is not None and number > spec.maximum:
        raise SettingsError(f"{spec.label} must be at most {_european(spec.maximum)} °C.")
    return number
