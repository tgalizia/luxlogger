"""Dashboard mode line and status badges.

Operating mode is the job (heating, hot water, and so on). The status line is
what the machine is doing at that moment. They often overlap, so the card
lights a job badge, an activity badge, or both when each one is actually on.
"""

from dataclasses import dataclass

_JOBS = {
    "heating": "Heating",
    "hot water": "Hot water",
    "swimming pool/solar": "Pool",
    "evu": "Utility lock",
    "defrost": "Defrost",
    "heating external source": "Backup heater",
    "cooling": "Cooling",
}

_ACTIVITIES = {
    "heatpump idle": "Idle",
    "heatpump coming": "Starting soon",
    "errorcode slot 0": "Fault",
    "defrost": "Defrost",
    "witing on LIN connection": "Waiting for the indoor unit",
    "compressor heating up": "Compressor warming up",
    "pump forerun": "Pump pre-run",
}

_QUIET_WHEN_IDLE = {"Utility lock", "Backup heater"}


def describe_mode(operating_mode: str | None, status_line: str | None) -> str:
    """Return the single phrase shown on the mode card."""
    job = _job(operating_mode)
    activity = _activity(status_line)
    if activity == "Idle" and job in _QUIET_WHEN_IDLE:
        activity = None
    if job and activity and job != activity:
        return f"{job}, {_lower_first(activity)}"
    if job:
        return job
    if activity:
        return activity
    if operating_mode == "no request":
        return "No request"
    return "—"


def _job(operating_mode: str | None) -> str | None:
    if not operating_mode or operating_mode == "no request":
        return None
    return _JOBS.get(operating_mode, operating_mode)


def _activity(status_line: str | None) -> str | None:
    if not status_line or status_line == "heatpump running":
        return None
    return _ACTIVITIES.get(status_line, status_line)


def _lower_first(text: str) -> str:
    return text[0].lower() + text[1:]


@dataclass(frozen=True)
class _Badge:
    id: str
    label: str
    tone: str
    always: bool = True


# Rare states stay out of the row until they switch on.
_BADGES = (
    _Badge("idle", "Idle", "idle"),
    _Badge("pump", "Pump pre-run", "pump"),
    _Badge("starting", "Starting", "starting"),
    _Badge("heating", "Heating", "heat"),
    _Badge("hot_water", "Hot water", "water"),
    _Badge("defrost", "Defrost", "defrost"),
    _Badge("cooling", "Cooling", "cool"),
    _Badge("backup", "Backup", "backup"),
    _Badge("fault", "Fault", "fault"),
    _Badge("pool", "Pool", "pool", always=False),
    _Badge("lock", "Utility lock", "lock", always=False),
    _Badge("warmup", "Warm-up", "warmup", always=False),
    _Badge("link", "Indoor link", "link", always=False),
)

_MODE_BADGES = {
    "heating": "heating",
    "hot water": "hot_water",
    "swimming pool/solar": "pool",
    "evu": "lock",
    "defrost": "defrost",
    "heating external source": "backup",
    "cooling": "cooling",
}

_STATUS_BADGES = {
    "heatpump running": None,
    "heatpump idle": "idle",
    "heatpump coming": "starting",
    "errorcode slot 0": "fault",
    "defrost": "defrost",
    "witing on LIN connection": "link",
    "compressor heating up": "warmup",
    "pump forerun": "pump",
}


def mode_badges(operating_mode: str | None, status_line: str | None) -> list[dict]:
    """Badges for the mode card. `on` is the one currently lit."""
    active = _active_badge_ids(operating_mode, status_line)
    return [
        {"id": badge.id, "label": badge.label, "tone": badge.tone, "on": badge.id in active}
        for badge in _BADGES
        if badge.always or badge.id in active
    ]


def _active_badge_ids(operating_mode: str | None, status_line: str | None) -> set[str]:
    active: set[str] = set()
    job = _MODE_BADGES.get(operating_mode or "")
    if job:
        active.add(job)
    if status_line in _STATUS_BADGES:
        step = _STATUS_BADGES[status_line]
        if step:
            active.add(step)
    if not active and operating_mode == "no request":
        active.add("idle")
    return active
