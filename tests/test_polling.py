"""Paused queries must not open the controller socket."""

from types import SimpleNamespace

from app.luxtronik_client import QueriesPaused, ensure_polling, poll_once, poll_state


def test_paused_poll_does_not_open_the_controller(monkeypatch):
    def fail_read(*_args, **_kwargs):
        raise AssertionError("controller queried")

    monkeypatch.setattr("app.luxtronik_client.read_live_snapshot", fail_read)
    monkeypatch.setattr(
        "app.luxtronik_client.get_settings",
        lambda: SimpleNamespace(demo_mode=False, poll_interval_seconds=60),
    )
    poll_state.set_polling(False)
    try:
        poll_once()
        try:
            ensure_polling()
        except QueriesPaused as exc:
            assert "paused" in str(exc)
        else:
            raise AssertionError("paused queries were allowed")
    finally:
        poll_state.set_polling(True)
