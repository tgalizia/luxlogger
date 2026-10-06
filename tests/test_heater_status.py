"""Extra-heater on/off is the digital output, with the session timer as fallback."""

from app.luxtronik_client import derive_heater_running


def test_any_closed_output_means_the_heater_is_on():
    assert derive_heater_running(True, False, None, runtime=0) is True


def test_open_outputs_mean_off_even_if_the_timer_has_not_cleared():
    assert derive_heater_running(False, False, False, runtime=40) is False


def test_session_timer_is_used_when_outputs_are_missing():
    assert derive_heater_running(None, None, None, runtime=12) is True
    assert derive_heater_running(None, None, None, runtime=0) is False
    assert derive_heater_running(None, None, None, runtime=None) is False
