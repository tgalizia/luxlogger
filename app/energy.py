"""Heat-meter deltas and the cost of that delivered heat."""

CHANNELS = (
    ("heating", "Heating", "heat_heating_kwh"),
    ("hot_water", "Hot water", "heat_dhw_kwh"),
    ("pool", "Pool", "heat_pool_kwh"),
)

MAX_PRICE_PER_KWH = 100


class PriceError(Exception):
    """A manually entered price or currency label cannot be stored."""


def validate_price(value) -> float:
    """Return a price per kWh, or raise PriceError."""
    if isinstance(value, bool) or value is None or (isinstance(value, str) and not str(value).strip()):
        raise PriceError("Enter a price per kWh.")
    try:
        number = round(float(value), 4)
    except (TypeError, ValueError):
        raise PriceError("Enter a price per kWh.") from None
    if number < 0:
        raise PriceError("The price per kWh cannot be negative.")
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


def delivered_kwh(samples, attr: str) -> float | None:
    """Sum increases of one cumulative counter. A drop restarts from the new reading."""
    values = []
    for sample in samples:
        value = getattr(sample, attr, None)
        if value is None:
            continue
        values.append(float(value))
    if len(values) < 2:
        return None
    total = 0.0
    previous = values[0]
    for value in values[1:]:
        if value + 1e-6 >= previous:
            total += value - previous
        else:
            total += value
        previous = value
    return round(total, 1)


def energy_report(samples, latest, price: float | None, currency: str, since_iso: str | None) -> dict:
    """Period heat and cost, plus the current meter readings."""
    period = [
        _channel(channel_id, label, delivered_kwh(samples, attr), price)
        for channel_id, label, attr in CHANNELS
    ]
    meter = [
        _channel(channel_id, label, _meter_kwh(latest, attr), price)
        for channel_id, label, attr in CHANNELS
    ]
    return {
        "since": since_iso,
        "price_per_kwh": price,
        "currency": currency,
        "period": {"channels": period, "total": _total(period, price)},
        "meter": {"channels": meter, "total": _total(meter, price)},
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
