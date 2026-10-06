"""Heat-meter deltas and the priced energy response. These tests do not open a socket."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.energy import PriceError, delivered_kwh, energy_report, validate_currency, validate_price
from app.luxtronik_client import demo_snapshot


def _sample(**values):
    fields = {"heat_heating_kwh": None, "heat_dhw_kwh": None, "heat_pool_kwh": None}
    fields.update(values)
    return SimpleNamespace(**fields)


def test_delivered_heat_sums_a_steady_rise():
    samples = [
        _sample(heat_heating_kwh=10.0),
        _sample(heat_heating_kwh=10.5),
        _sample(heat_heating_kwh=12.0),
    ]
    assert delivered_kwh(samples, "heat_heating_kwh") == 2.0


def test_delivered_heat_restarts_after_a_reset():
    samples = [
        _sample(heat_heating_kwh=100),
        _sample(heat_heating_kwh=110),
        _sample(heat_heating_kwh=5),
        _sample(heat_heating_kwh=8),
    ]
    assert delivered_kwh(samples, "heat_heating_kwh") == 18.0


def test_one_reading_has_no_period_figure():
    assert delivered_kwh([_sample(heat_heating_kwh=4)], "heat_heating_kwh") is None
    assert delivered_kwh([_sample(), _sample()], "heat_heating_kwh") is None


def test_price_must_be_a_european_number_up_to_100():
    assert validate_price("0,32") == 0.32
    assert validate_price(" 12,50 ") == 12.5
    assert validate_price("0,00") == 0
    assert validate_price("100,00") == 100
    assert validate_currency(None) == "€"
    assert validate_currency("  ") == "€"
    for value in (None, "", "0.32", "0,3", "0,321", "100,01", "abc", 0.32, 0, 100, True):
        with pytest.raises(PriceError):
            validate_price(value)
    with pytest.raises(PriceError):
        validate_currency("euros")


def test_energy_report_prices_only_the_range():
    samples = [
        _sample(heat_heating_kwh=100, heat_dhw_kwh=40, heat_pool_kwh=0),
        _sample(heat_heating_kwh=110, heat_dhw_kwh=42, heat_pool_kwh=0),
    ]
    report = energy_report(samples, samples[-1], 0.3, "€", "2026-10-01T00:00:00Z")
    heating = report["period"]["channels"][0]
    assert heating["kwh"] == 10
    assert heating["cost"] == 3
    assert report["period"]["total"] == {"kwh": 12, "cost": 3.6}
    assert report["meter"]["channels"][0] == {"id": "heating", "label": "Heating", "kwh": 110, "cost": None}
    assert report["meter"]["total"]["kwh"] == 152
    assert report["meter"]["total"]["cost"] is None
    assert report["price_per_kwh"] == 0.3


def test_energy_report_omits_cost_without_a_price():
    samples = [
        _sample(heat_heating_kwh=1, heat_dhw_kwh=1, heat_pool_kwh=0),
        _sample(heat_heating_kwh=2, heat_dhw_kwh=1, heat_pool_kwh=0),
    ]
    report = energy_report(samples, samples[-1], None, "€", "2026-10-01T00:00:00Z")
    assert report["price_per_kwh"] is None
    assert report["period"]["channels"][0]["kwh"] == 1
    assert report["period"]["channels"][0]["cost"] is None
    assert report["period"]["total"]["cost"] is None
    assert report["meter"]["total"]["kwh"] == 3
    assert report["meter"]["total"]["cost"] is None


def test_demo_heat_counters_rise():
    early = demo_snapshot(datetime(2026, 1, 1, tzinfo=timezone.utc))
    late = demo_snapshot(datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert late.heat_heating_kwh > early.heat_heating_kwh
    assert late.heat_dhw_kwh > early.heat_dhw_kwh
    assert early.heat_pool_kwh == 0
    assert late.heat_pool_kwh == 0
