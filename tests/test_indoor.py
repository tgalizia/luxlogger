"""Room temperature source. These tests do not open a socket."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.database import Base, IndoorTemperature
from app.main import IndoorIn, create_indoor, shelly_indoor
from app.runtime import (
    PreferenceError,
    record_luxtronik_reading,
    save_app_settings,
    validate_indoor_room,
    validate_indoor_source,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    opened = sessionmaker(bind=engine)()
    try:
        yield opened
    finally:
        opened.close()
        engine.dispose()


def choose(session, source, room="living room"):
    save_app_settings(
        session,
        {"indoor_source", "indoor_room"},
        SimpleNamespace(indoor_source=source, indoor_room=room),
    )


def indoor_count(session) -> int:
    return session.scalar(select(func.count()).select_from(IndoorTemperature))


def test_unknown_source_is_rejected():
    with pytest.raises(PreferenceError):
        validate_indoor_source("bluetooth")


def test_blank_room_uses_living_room():
    assert validate_indoor_room("  ") == "living room"


def test_long_room_name_is_rejected():
    with pytest.raises(PreferenceError):
        validate_indoor_room("room " * 20)


def test_shelly_request_stores_the_saved_room(session):
    choose(session, "shelly", "kitchen")
    saved = shelly_indoor(21.5, session)
    assert saved["temperature_c"] == 21.5
    assert saved["room"] == "kitchen"
    assert indoor_count(session) == 1


def test_shelly_request_is_rejected_when_another_source_is_selected(session):
    choose(session, "manual")
    with pytest.raises(HTTPException) as exc:
        shelly_indoor(21.5, session)
    assert exc.value.status_code == 409
    assert indoor_count(session) == 0


def test_shelly_request_rejects_a_temperature_outside_range(session):
    choose(session, "shelly")
    with pytest.raises(HTTPException) as exc:
        shelly_indoor(46, session)
    assert exc.value.status_code == 422
    assert indoor_count(session) == 0


def test_hand_entry_is_rejected_when_a_sensor_is_selected(session):
    choose(session, "luxtronik")
    with pytest.raises(HTTPException) as exc:
        create_indoor(IndoorIn(temperature_c=21.5), session)
    assert exc.value.status_code == 409
    assert indoor_count(session) == 0


def test_hand_entry_stores_when_that_source_is_selected(session):
    saved = create_indoor(IndoorIn(temperature_c=20.0, room="hall"), session)
    assert saved["temperature_c"] == 20.0
    assert saved["room"] == "hall"


def test_luxtronik_value_is_stored_only_in_range_for_that_source(session):
    assert record_luxtronik_reading(session, 21.5) is None
    assert indoor_count(session) == 0
    choose(session, "luxtronik", "living room")
    assert record_luxtronik_reading(session, None) is None
    assert record_luxtronik_reading(session, -999.9) is None
    assert record_luxtronik_reading(session, 46) is None
    assert indoor_count(session) == 0
    row = record_luxtronik_reading(session, 21.5)
    assert row.temperature_c == 21.5
    assert row.room == "living room"
    assert record_luxtronik_reading(session, -10).temperature_c == -10
    assert record_luxtronik_reading(session, 45).temperature_c == 45
    assert indoor_count(session) == 3
