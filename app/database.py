"""SQLite persistence. Swap DATABASE_URL for PostgreSQL without changing models."""

import json
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, create_engine, event, func, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.config import resolved_database_url


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def isoformat_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class Base(DeclarativeBase):
    pass


class TelemetrySample(Base):
    __tablename__ = "telemetry_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    flow_temp: Mapped[float | None] = mapped_column(Float)
    return_temp: Mapped[float | None] = mapped_column(Float)
    outdoor_temp: Mapped[float | None] = mapped_column(Float)
    dhw_temp: Mapped[float | None] = mapped_column(Float)
    dhw_setpoint: Mapped[float | None] = mapped_column(Float)
    return_setpoint: Mapped[float | None] = mapped_column(Float)
    flow_rate: Mapped[float | None] = mapped_column(Float)
    heatpump_code: Mapped[str | None] = mapped_column(String(64))
    operating_mode: Mapped[str | None] = mapped_column(String(64))
    compressor_hz: Mapped[float | None] = mapped_column(Float)
    compressor_runtime_s: Mapped[float | None] = mapped_column(Float)
    compressor_total_s: Mapped[float | None] = mapped_column(Float)
    compressor_running: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    bivalence_stage: Mapped[str | None] = mapped_column(String(80))
    backup_heater_runtime_s: Mapped[float | None] = mapped_column(Float)
    backup_heater_total_s: Mapped[float | None] = mapped_column(Float)
    backup_heater_running: Mapped[bool | None] = mapped_column(Boolean)
    status_line: Mapped[str | None] = mapped_column(String(80))
    heat_heating_kwh: Mapped[float | None] = mapped_column(Float)
    heat_dhw_kwh: Mapped[float | None] = mapped_column(Float)
    heat_pool_kwh: Mapped[float | None] = mapped_column(Float)


class IndoorTemperature(Base):
    __tablename__ = "indoor_temperatures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room: Mapped[str] = mapped_column(String(80), nullable=False, default="living room")
    temperature_c: Mapped[float] = mapped_column(Float, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)


class AdvisorReport(Base):
    __tablename__ = "advisor_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    findings_json: Mapped[str] = mapped_column(Text, nullable=False)
    suggestion: Mapped[str] = mapped_column(Text, nullable=False)


class SettingChange(Base):
    __tablename__ = "setting_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    setting_id: Mapped[str] = mapped_column(String(64), nullable=False)
    old_value: Mapped[str] = mapped_column(String(64), nullable=False)
    new_value: Mapped[str] = mapped_column(String(64), nullable=False)
    from_suggestion: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AppPreference(Base):
    __tablename__ = "app_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    price_per_kwh: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="€")
    luxtronik_host: Mapped[str | None] = mapped_column(String(255))
    luxtronik_port: Mapped[int | None] = mapped_column(Integer)
    pump_maker: Mapped[str | None] = mapped_column(String(120))
    pump_model: Mapped[str | None] = mapped_column(String(120))
    controller_model: Mapped[str | None] = mapped_column(String(120))
    controller_software: Mapped[str | None] = mapped_column(String(120))
    ai_provider: Mapped[str | None] = mapped_column(String(32))
    ai_model: Mapped[str | None] = mapped_column(String(128))
    advice_prompt: Mapped[str | None] = mapped_column(Text)
    settings_prompt: Mapped[str | None] = mapped_column(Text)


def _connect_args(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"check_same_thread": False, "timeout": 30}
    return {}


_database_url = resolved_database_url()
engine = create_engine(_database_url, connect_args=_connect_args(_database_url))
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, _connection_record):
    if engine.dialect.name != "sqlite":
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


_TELEMETRY_COLUMNS = {
    "backup_heater_running": "BOOLEAN",
    "heat_heating_kwh": "FLOAT",
    "heat_dhw_kwh": "FLOAT",
    "heat_pool_kwh": "FLOAT",
    "dhw_setpoint": "FLOAT",
}

_PREFERENCE_COLUMNS = {
    "luxtronik_host": "VARCHAR(255)",
    "luxtronik_port": "INTEGER",
    "pump_maker": "VARCHAR(120)",
    "pump_model": "VARCHAR(120)",
    "controller_model": "VARCHAR(120)",
    "controller_software": "VARCHAR(120)",
    "ai_provider": "VARCHAR(32)",
    "ai_model": "VARCHAR(128)",
    "advice_prompt": "TEXT",
    "settings_prompt": "TEXT",
}


def _missing_columns(table: str, columns: dict[str, str]) -> list[str]:
    existing = {column["name"] for column in inspect(engine).get_columns(table)}
    return [
        f"ALTER TABLE {table} ADD COLUMN {name} {kind}"
        for name, kind in columns.items()
        if name not in existing
    ]


def init_db() -> None:
    Base.metadata.create_all(engine)
    missing = _missing_columns(TelemetrySample.__tablename__, _TELEMETRY_COLUMNS)
    missing.extend(_missing_columns(AppPreference.__tablename__, _PREFERENCE_COLUMNS))
    if missing:
        with engine.begin() as connection:
            for statement in missing:
                connection.execute(text(statement))


@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _round(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def sample_to_dict(row: TelemetrySample) -> dict:
    return {
        "id": row.id,
        "recorded_at": isoformat_utc(row.recorded_at),
        "flow_temp": _round(row.flow_temp, 1),
        "return_temp": _round(row.return_temp, 1),
        "outdoor_temp": _round(row.outdoor_temp, 1),
        "dhw_temp": _round(row.dhw_temp, 1),
        "dhw_setpoint": _round(row.dhw_setpoint, 1),
        "return_setpoint": _round(row.return_setpoint, 1),
        "flow_rate": _round(row.flow_rate, 0),
        "heatpump_code": row.heatpump_code,
        "operating_mode": row.operating_mode,
        "compressor_hz": _round(row.compressor_hz, 0),
        "compressor_runtime_s": _round(row.compressor_runtime_s, 0),
        "compressor_total_s": _round(row.compressor_total_s, 0),
        "compressor_running": bool(row.compressor_running),
        "bivalence_stage": row.bivalence_stage,
        "backup_heater_runtime_s": _round(row.backup_heater_runtime_s, 0),
        "backup_heater_total_s": _round(row.backup_heater_total_s, 0),
        "backup_heater_running": None if row.backup_heater_running is None else bool(row.backup_heater_running),
        "status_line": row.status_line,
        "heat_heating_kwh": _round(row.heat_heating_kwh, 1),
        "heat_dhw_kwh": _round(row.heat_dhw_kwh, 1),
        "heat_pool_kwh": _round(row.heat_pool_kwh, 1),
    }


def indoor_to_dict(row: IndoorTemperature) -> dict:
    return {
        "id": row.id,
        "room": row.room,
        "temperature_c": _round(row.temperature_c, 1),
        "recorded_at": isoformat_utc(row.recorded_at),
    }


def report_to_dict(row: AdvisorReport) -> dict:
    return {
        "id": row.id,
        "created_at": isoformat_utc(row.created_at),
        "provider": row.provider,
        "model": row.model,
        "findings": json.loads(row.findings_json),
        "suggestion": row.suggestion,
    }


def add_sample(session, snapshot) -> TelemetrySample:
    row = TelemetrySample(
        recorded_at=snapshot.recorded_at,
        flow_temp=snapshot.flow_temp,
        return_temp=snapshot.return_temp,
        outdoor_temp=snapshot.outdoor_temp,
        dhw_temp=snapshot.dhw_temp,
        dhw_setpoint=snapshot.dhw_setpoint,
        return_setpoint=snapshot.return_setpoint,
        flow_rate=snapshot.flow_rate,
        heatpump_code=snapshot.heatpump_code,
        operating_mode=snapshot.operating_mode,
        compressor_hz=snapshot.compressor_hz,
        compressor_runtime_s=snapshot.compressor_runtime_s,
        compressor_total_s=snapshot.compressor_total_s,
        compressor_running=snapshot.compressor_running,
        bivalence_stage=snapshot.bivalence_stage,
        backup_heater_runtime_s=snapshot.backup_heater_runtime_s,
        backup_heater_total_s=snapshot.backup_heater_total_s,
        backup_heater_running=snapshot.backup_heater_running,
        status_line=snapshot.status_line,
        heat_heating_kwh=snapshot.heat_heating_kwh,
        heat_dhw_kwh=snapshot.heat_dhw_kwh,
        heat_pool_kwh=snapshot.heat_pool_kwh,
    )
    session.add(row)
    return row


def count_samples(session) -> int:
    return session.scalar(select(func.count()).select_from(TelemetrySample)) or 0


def latest_sample(session) -> TelemetrySample | None:
    return session.scalar(select(TelemetrySample).order_by(TelemetrySample.recorded_at.desc()).limit(1))


def samples_since(session, since: datetime) -> list[TelemetrySample]:
    return list(
        session.scalars(
            select(TelemetrySample)
            .where(TelemetrySample.recorded_at >= since)
            .order_by(TelemetrySample.recorded_at.asc())
        )
    )


def add_indoor(session, room: str, temperature_c: float, recorded_at: datetime | None = None) -> IndoorTemperature:
    row = IndoorTemperature(
        room=room,
        temperature_c=temperature_c,
        recorded_at=recorded_at or utcnow(),
    )
    session.add(row)
    return row


def latest_indoor(session) -> IndoorTemperature | None:
    return session.scalar(select(IndoorTemperature).order_by(IndoorTemperature.recorded_at.desc()).limit(1))


def indoor_since(session, since: datetime) -> list[IndoorTemperature]:
    return list(
        session.scalars(
            select(IndoorTemperature)
            .where(IndoorTemperature.recorded_at >= since)
            .order_by(IndoorTemperature.recorded_at.asc())
        )
    )


def recent_indoor(session, limit: int = 50) -> list[IndoorTemperature]:
    rows = list(
        session.scalars(select(IndoorTemperature).order_by(IndoorTemperature.recorded_at.desc()).limit(limit))
    )
    rows.reverse()
    return rows


def add_report(session, provider: str, model: str, findings: dict, suggestion: str) -> AdvisorReport:
    row = AdvisorReport(
        created_at=utcnow(),
        provider=provider,
        model=model,
        findings_json=json.dumps(findings),
        suggestion=suggestion,
    )
    session.add(row)
    return row


def latest_report(session) -> AdvisorReport | None:
    return session.scalar(select(AdvisorReport).order_by(AdvisorReport.created_at.desc()).limit(1))


def add_setting_change(
    session,
    setting_id: str,
    old_value: str,
    new_value: str,
    from_suggestion: bool,
) -> SettingChange:
    row = SettingChange(
        created_at=utcnow(),
        setting_id=setting_id,
        old_value=old_value,
        new_value=new_value,
        from_suggestion=from_suggestion,
    )
    session.add(row)
    return row


def get_app_preference(session) -> AppPreference | None:
    return session.scalar(select(AppPreference).order_by(AppPreference.id).limit(1))


def preference_to_dict(row: AppPreference | None) -> dict:
    if row is None or row.price_per_kwh is None:
        currency = "€" if row is None or not row.currency else row.currency
        return {"price_per_kwh": None, "currency": currency}
    return {"price_per_kwh": round(float(row.price_per_kwh), 4), "currency": row.currency or "€"}


def apply_app_preference(session, **fields) -> AppPreference:
    """Update only the given columns. A missing row starts with the euro symbol."""
    row = get_app_preference(session)
    if row is None:
        row = AppPreference(currency=fields.get("currency") or "€")
        session.add(row)
    for key, value in fields.items():
        setattr(row, key, value)
    return row


def save_app_preference(session, price_per_kwh: float, currency: str) -> AppPreference:
    return apply_app_preference(session, price_per_kwh=price_per_kwh, currency=currency)
