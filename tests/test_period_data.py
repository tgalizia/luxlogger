"""Period export. These tests do not open a socket."""

from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, add_indoor, add_sample, isoformat_utc, utcnow
from app.luxtronik_client import Snapshot
from app.main import period_data


def memory_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def snap(when, **kwargs):
    fields = dict(
        recorded_at=when,
        flow_temp=35.0,
        return_temp=30.0,
        outdoor_temp=5.0,
        dhw_temp=45.0,
        dhw_setpoint=46.0,
        return_setpoint=30.0,
        flow_rate=1000.0,
        heatpump_code="LWC",
        operating_mode="heating",
        compressor_hz=40.0,
        compressor_runtime_s=0.0,
        compressor_total_s=0.0,
        compressor_running=False,
        bivalence_stage="one compressor allowed to run",
        backup_heater_runtime_s=0.0,
        backup_heater_total_s=0.0,
        backup_heater_running=False,
        status_line="heatpump idle",
        heat_heating_kwh=10.0,
        heat_dhw_kwh=5.0,
        heat_pool_kwh=0.0,
    )
    fields.update(kwargs)
    return Snapshot(**fields)


def test_period_data_keeps_rows_inside_the_window():
    session = memory_session()
    start = utcnow() - timedelta(hours=2)
    end = start + timedelta(hours=1)
    inside = start + timedelta(minutes=30)
    add_sample(session, snap(start - timedelta(minutes=1), flow_temp=10.0))
    add_sample(session, snap(inside, flow_temp=35.0))
    add_indoor(session, "hall", 18.0, start - timedelta(minutes=1))
    add_indoor(session, "living room", 21.5, inside)
    session.flush()

    result = period_data(session, start, end)

    assert result["since"] == isoformat_utc(start)
    assert result["until"] == isoformat_utc(end)
    assert [row["flow_temp"] for row in result["samples"]] == [35.0]
    assert [(row["room"], row["temperature_c"]) for row in result["indoor"]] == [("living room", 21.5)]
