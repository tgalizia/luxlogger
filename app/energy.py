"""Heat-meter deltas and the cost of heat delivered in a selected range."""

import re
from datetime import datetime

CHANNELS = (
    ("heating", "Heating", "heat_heating_kwh"),
    ("hot_water", "Hot water", "heat_dhw_kwh"),
    ("pool", "Pool", "heat_pool_kwh"),
)

MAX_PRICE_PER_KWH = 100
# A household heat pump cannot deliver more than this between two readings.
MAX_HEAT_KW = 100
# A step backward of at most this much is meter noise, not a reset.
NOISE_KWH = 1.0
_EUROPEAN_PRICE = re.compile(r"^\d{1,3},\d{2}$")


class PriceError(Exception):
    """A manually entered price or currency label cannot be stored."""


def validate_price(value) -> float:
    """Return a price per kWh from a European number such as 0,30."""
    if not isinstance(value, str) or not _EUROPEAN_PRICE.fullmatch(value.strip()):
        raise PriceError("Enter the price as a European number, for example 0,30.")
    number = round(float(value.strip().replace(",", ".")), 2)
    if number > MAX_PRICE_PER_KWH:
        raise PriceError("The price per kWh must be at most 100.")
    return number


def validate_currency(value) -> str:
    """Return a short currency label. An empty value stays €."""
    if value is None:
        return "€"
    text = str(value).strip()
    if not text:
        return "€"
    if len(text) > 4:
        raise PriceError("Use a currency label of at most 4 characters.")
    return text


def _elapsed_hours(earlier, later) -> float | None:
    start = getattr(earlier, "recorded_at", None)
    end = getattr(later, "recorded_at", None)
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        return None
    if (start.tzinfo is None) != (end.tzinfo is None):
        return None
    seconds = (end - start).total_seconds()
    if seconds < 0:
        return None
    return seconds / 3600


def _step_limit(earlier, later) -> float | None:
    """Most heat a house can deliver since the previous accepted reading."""
    hours = _elapsed_hours(earlier, later)
    if hours is None:
        return None
    return max(NOISE_KWH, MAX_HEAT_KW * hours)


def _backward_noise(previous: float, value: float) -> bool:
    return previous - value <= NOISE_KWH + 1e-6


def _recovers(baseline: float, later: list[float]) -> bool:
    """True when a later reading climbs back to the counter from before a dip."""
    return any(value + 1e-6 >= baseline for value in later)


def _readings(samples, attr: str) -> list[tuple]:
    readings = []
    for sample in samples:
        value = getattr(sample, attr, None)
        if value is None:
            continue
        readings.append((sample, float(value)))
    return readings


def _cumulative(samples, attr: str) -> list[float]:
    """Running heat from the first reading. Noise and one-off glitches are skipped."""
    readings = _readings(samples, attr)
    if not readings:
        return []
    total = 0.0
    series = [0.0]
    prev_sample, prev = readings[0]
    for index, (sample, value) in enumerate(readings[1:], start=1):
        later = [item for _, item in readings[index + 1 :]]
        limit = _step_limit(prev_sample, sample)
        if value + 1e-6 >= prev:
            delta = value - prev
            if limit is None or delta <= limit + 1e-6:
                total += delta
                prev_sample, prev = sample, value
        elif _backward_noise(prev, value) or _recovers(prev, later):
            pass
        else:
            # The counter restarted and stayed down. Count heat since zero
            # only when that reading could have been produced in the gap.
            if limit is None or value <= limit + 1e-6:
                total += value
            prev_sample, prev = sample, value
        series.append(round(total, 1))
    return series


def delivered_kwh(samples, attr: str) -> float | None:
    """Heat added by one cumulative counter. A small dip is not a reset."""
    if len(_readings(samples, attr)) < 2:
        return None
    series = _cumulative(samples, attr)
    return series[-1]


def cumulative_kwh(samples, attr: str) -> list[float]:
    """Running heat delivered from the first reading in the window."""
    return _cumulative(samples, attr)


def energy_report(samples, latest, price: float | None, currency: str, since_iso: str | None) -> dict:
    """Period heat and cost, plus the current meter readings without a price."""
    period = [
        _channel(channel_id, label, delivered_kwh(samples, attr), price)
        for channel_id, label, attr in CHANNELS
    ]
    meter = [
        _channel(channel_id, label, _meter_kwh(latest, attr), None)
        for channel_id, label, attr in CHANNELS
    ]
    return {
        "since": since_iso,
        "price_per_kwh": price,
        "currency": currency,
        "period": {"channels": period, "total": _total(period, price)},
        "meter": {"channels": meter, "total": _total(meter, None)},
        "samples": len(samples),
    }


def _channel(channel_id: str, label: str, kwh: float | None, price: float | None) -> dict:
    return {
        "id": channel_id,
        "label": label,
        "kwh": kwh,
        "cost": None if kwh is None or price is None else round(kwh * price, 2),
    }


def _meter_kwh(latest, attr: str) -> float | None:
    if latest is None:
        return None
    value = getattr(latest, attr, None)
    if value is None:
        return None
    return round(float(value), 1)


def _total(channels: list[dict], price: float | None) -> dict:
    known = [channel for channel in channels if channel["kwh"] is not None]
    if not known:
        return {"kwh": None, "cost": None}
    kwh = round(sum(channel["kwh"] for channel in known), 1)
    if price is None:
        return {"kwh": kwh, "cost": None}
    return {"kwh": kwh, "cost": round(sum(channel["cost"] for channel in known), 2)}
