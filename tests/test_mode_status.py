from app.mode_status import describe_mode, mode_badges


def test_pump_prerun_without_a_job_is_one_phrase():
    assert describe_mode("no request", "pump forerun") == "Pump pre-run"


def test_idle_with_no_request_is_idle():
    assert describe_mode("no request", "heatpump idle") == "Idle"


def test_a_running_job_does_not_repeat_that_it_is_running():
    assert describe_mode("heating", "heatpump running") == "Heating"
    assert describe_mode("hot water", "heatpump running") == "Hot water"
    assert describe_mode("cooling", "heatpump running") == "Cooling"


def test_a_job_keeps_a_step_that_is_not_the_job_itself():
    assert describe_mode("heating", "pump forerun") == "Heating, pump pre-run"
    assert describe_mode("hot water", "heatpump coming") == "Hot water, starting soon"
    assert describe_mode("heating", "heatpump idle") == "Heating, idle"


def test_defrost_is_not_repeated():
    assert describe_mode("defrost", "defrost") == "Defrost"


def test_utility_lock_and_backup_heat_stand_alone_when_idle():
    assert describe_mode("evu", "heatpump idle") == "Utility lock"
    assert describe_mode("heating external source", "heatpump idle") == "Backup heater"


def test_missing_values():
    assert describe_mode(None, None) == "—"
    assert describe_mode("no request", None) == "No request"


def _lit(operating_mode, status_line):
    return {badge["id"] for badge in mode_badges(operating_mode, status_line) if badge["on"]}


def test_only_the_current_step_lights_during_a_pump_prerun():
    assert _lit("no request", "pump forerun") == {"pump"}


def test_idle_lights_on_its_own():
    assert _lit("no request", "heatpump idle") == {"idle"}


def test_a_running_job_lights_that_job():
    assert _lit("heating", "heatpump running") == {"heating"}
    assert _lit("hot water", "heatpump running") == {"hot_water"}


def test_a_job_and_a_step_can_both_be_lit():
    assert _lit("heating", "pump forerun") == {"heating", "pump"}
    assert _lit("hot water", "heatpump coming") == {"hot_water", "starting"}


def test_rare_badges_appear_only_while_they_are_on():
    quiet = {badge["id"] for badge in mode_badges("heating", "heatpump running")}
    assert "lock" not in quiet
    assert "pool" not in quiet
    locked = mode_badges("evu", "heatpump idle")
    assert {badge["id"] for badge in locked if badge["on"]} == {"lock", "idle"}
    assert any(badge["id"] == "lock" for badge in locked)
