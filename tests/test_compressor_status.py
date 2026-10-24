"""Compressor on/off is the relay, with status as a fallback when the relay is missing."""

from app.luxtronik_client import derive_compressor_running


def test_a_closed_relay_means_the_compressor_is_on():
    assert derive_compressor_running("pump forerun", True, 0, 1, "heating") is True


def test_an_open_relay_means_off_during_pre_run():
    assert derive_compressor_running("pump forerun", False, 0, 1, "heating") is False
    assert derive_compressor_running("heatpump running", False, 30, 1, "heating") is False
    assert derive_compressor_running("defrost", False, 0, 5, "defrost") is False


def test_status_is_used_only_when_the_relay_was_not_read():
    assert derive_compressor_running("heatpump idle", None, 0, 1, "heating") is False
    assert derive_compressor_running("heatpump running", None, 0, 0, "heating") is True
    assert derive_compressor_running("pump forerun", None, 0, 1, "heating") is True
    assert derive_compressor_running("defrost", None, 0, 0, "off") is True
    assert derive_compressor_running(None, None, 0, 0, "off") is False
