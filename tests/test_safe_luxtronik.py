"""The controller socket closes after every read, including a timeout."""

import socket
import threading
from datetime import datetime, timezone

import pytest

from app.luxtronik_client import (
    QueriesPaused,
    SettingsWriteError,
    poll_state,
    read_live_snapshot,
    read_pump_info,
    read_settings,
)
from app.safe_luxtronik import SOCKET_TIMEOUT_SECONDS, SafeLuxtronik, controller_lock


class _Bag:
    def get(self, _name):
        return None


def _replace_io(pump, events, fail_at=None):
    def connect():
        events.append("connect")
        pump._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    def parameters():
        events.append("parameters")
        if fail_at == "parameters":
            raise socket.timeout("timed out")

    def calculations():
        events.append("calculations")
        if fail_at == "calculations":
            raise socket.timeout("timed out")

    def visibilities():
        events.append("visibilities")
        if fail_at == "visibilities":
            raise socket.timeout("timed out")

    pump._connect = connect
    pump._read_parameters = parameters
    pump._read_calculations = calculations
    pump._read_visibilities = visibilities


def test_calculation_timeout_closes_without_the_other_blocks():
    events = []
    pump = SafeLuxtronik("127.0.0.1", 9)
    _replace_io(pump, events, fail_at="calculations")
    try:
        with pytest.raises(socket.timeout):
            pump.read_calculations_only()
        assert events == ["connect", "calculations"]
        assert pump._socket is None
    finally:
        pump.disconnect()


def test_full_read_closes_when_the_last_block_fails():
    events = []
    pump = SafeLuxtronik("127.0.0.1", 9)
    _replace_io(pump, events, fail_at="visibilities")
    try:
        with pytest.raises(socket.timeout):
            pump.read()
        assert events == ["connect", "parameters", "calculations", "visibilities"]
        assert pump._socket is None
    finally:
        pump.disconnect()


def test_connect_failure_shuts_the_socket_down(monkeypatch):
    seen = {}

    class Sock:
        def settimeout(self, value):
            seen["timeout"] = value

        def connect(self, _addr):
            raise ConnectionRefusedError("refused")

        def shutdown(self, how):
            seen["shutdown"] = how

        def close(self):
            seen["closed"] = True

    monkeypatch.setattr("app.safe_luxtronik.socket.socket", lambda *_args, **_kwargs: Sock())
    pump = SafeLuxtronik("127.0.0.1", 9)
    with pytest.raises(ConnectionRefusedError):
        pump.read_calculations_only()
    assert seen["timeout"] == SOCKET_TIMEOUT_SECONDS == 4.0
    assert seen["shutdown"] == socket.SHUT_RDWR
    assert seen["closed"] is True
    assert pump._socket is None


def test_a_second_read_waits_until_the_first_socket_closes():
    release = threading.Event()
    inside = threading.Event()
    second_inside = threading.Event()
    first = SafeLuxtronik("127.0.0.1", 9)
    second = SafeLuxtronik("127.0.0.1", 9)
    _replace_io(first, [])
    _replace_io(second, [])

    def hold():
        inside.set()
        assert release.wait(2)

    first._read_calculations = hold
    second._read_calculations = lambda: second_inside.set()
    thread = threading.Thread(target=first.read_calculations_only)
    other = threading.Thread(target=second.read_calculations_only)
    started = False
    try:
        thread.start()
        assert inside.wait(2)
        got = controller_lock.acquire(blocking=False)
        if got:
            controller_lock.release()
        assert got is False
        other.start()
        started = True
        assert second_inside.wait(0.2) is False
    finally:
        release.set()
        thread.join(2)
        if started:
            other.join(2)
        first.disconnect()
        second.disconnect()
    assert second_inside.is_set()
    assert not thread.is_alive()
    assert not other.is_alive()


def test_snapshot_reads_only_calculations_and_trusts_the_relay(monkeypatch):
    class Field:
        def __init__(self, value):
            self.value = value

    values = {
        "ID_WEB_HauptMenuStatus_Zeile1": "pump forerun",
        "ID_WEB_WP_BZ_akt": "heating",
        "ID_WEB_Freq_VD": 0,
        "ID_WEB_Time_WPein_akt": 1,
        "ID_WEB_VD1out": False,
    }

    class Calculations:
        def get(self, name):
            if name not in values:
                return None
            return Field(values[name])

    calls = []

    class Pump:
        def __init__(self, host, port, safe=True):
            calls.append(("init", host, port))
            self.calculations = Calculations()

        def read_calculations_only(self):
            calls.append("calculations")

        def read(self):
            calls.append("full")

        def read_parameters_only(self):
            calls.append("parameters")

        def disconnect(self):
            calls.append("close")

    monkeypatch.setattr("app.luxtronik_client.SafeLuxtronik", Pump)
    poll_state.set_polling(True)
    snapshot = read_live_snapshot("10.0.0.1", 8888, datetime.now(timezone.utc))
    assert calls == [("init", "10.0.0.1", 8888), "calculations", "close"]
    assert snapshot.compressor_running is False
    assert snapshot.status_line == "pump forerun"
    assert snapshot.operating_mode == "heating"
    assert snapshot.compressor_runtime_s == 1


def test_settings_skip_calculations_and_the_info_page_reads_all_three(monkeypatch):
    calls = []

    class Pump:
        def __init__(self, host, port, safe=True):
            calls.append("init")
            self.parameters = _Bag()
            self.calculations = _Bag()
            self.visibilities = _Bag()

        def read_parameters_only(self):
            calls.append("parameters")

        def read(self):
            calls.append("full")

        def disconnect(self):
            calls.append("close")

    monkeypatch.setattr("app.luxtronik_client.SafeLuxtronik", Pump)
    poll_state.set_polling(True)
    with pytest.raises(SettingsWriteError):
        read_settings("127.0.0.1", 9)
    assert calls == ["init", "parameters", "close"]

    calls.clear()
    info = read_pump_info("127.0.0.1", 9)
    assert calls == ["init", "full", "close"]
    assert info["demo"] is False
    assert info["sections"]


def test_paused_snapshot_does_not_open_a_client(monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError("client created")

    monkeypatch.setattr("app.luxtronik_client.SafeLuxtronik", fail)
    poll_state.set_polling(False)
    try:
        with pytest.raises(QueriesPaused):
            read_live_snapshot("127.0.0.1", 9, datetime.now(timezone.utc))
    finally:
        poll_state.set_polling(True)
