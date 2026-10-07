"""App settings stored in the database, with .env as the fallback."""

from dataclasses import dataclass

from app.ai_advisor import (
    DEFAULT_MODELS,
    MODEL_CHOICES,
    SETTINGS_PROMPT,
    SYSTEM_PROMPT,
    AdvisorError,
    validate_model,
    validate_prompt,
    validate_provider,
)
from app.config import Settings, get_settings
from app.database import apply_app_preference, get_app_preference, preference_to_dict, session_scope

IDENTITY_LIMIT = 120


class PreferenceError(Exception):
    """An app setting cannot be stored."""


@dataclass(frozen=True)
class Runtime:
    settings: Settings
    host: str
    port: int
    provider: str
    model: str
    advice_prompt: str
    settings_prompt: str
    pump_maker: str
    pump_model: str
    controller_model: str
    controller_software: str

    def identity(self) -> dict:
        return {
            "pump_maker": self.pump_maker,
            "pump_model": self.pump_model,
            "controller_model": self.controller_model,
            "controller_software": self.controller_software,
        }


def effective_runtime(session=None) -> Runtime:
    """Overlay the saved app settings on the environment."""
    settings = get_settings()
    if session is None:
        with session_scope() as opened:
            return _from_row(get_app_preference(opened), settings)
    return _from_row(get_app_preference(session), settings)


def controller_endpoint(session=None) -> tuple[str, int]:
    runtime = effective_runtime(session)
    return runtime.host, runtime.port


def app_settings_payload(session) -> dict:
    row = get_app_preference(session)
    runtime = _from_row(row, get_settings())
    price = preference_to_dict(row)
    return {
        "price_per_kwh": price["price_per_kwh"],
        "currency": price["currency"],
        "luxtronik_host": runtime.host,
        "luxtronik_port": runtime.port,
        "pump_maker": runtime.pump_maker,
        "pump_model": runtime.pump_model,
        "controller_model": runtime.controller_model,
        "controller_software": runtime.controller_software,
        "ai_provider": runtime.provider,
        "ai_model": runtime.model,
        "advice_prompt": runtime.advice_prompt,
        "settings_prompt": runtime.settings_prompt,
        "advice_prompt_default": SYSTEM_PROMPT,
        "settings_prompt_default": SETTINGS_PROMPT,
        "model_choices": {provider: list(models) for provider, models in MODEL_CHOICES.items()},
    }


def save_app_settings(session, sent: set[str], body) -> dict:
    """Store only the fields the request included."""
    updates = {}
    if "price_per_kwh" in sent:
        from app.energy import validate_currency, validate_price

        updates["price_per_kwh"] = validate_price(body.price_per_kwh)
        updates["currency"] = validate_currency(body.currency)
    if "luxtronik_host" in sent or "luxtronik_port" in sent:
        if "luxtronik_host" not in sent or "luxtronik_port" not in sent:
            raise PreferenceError("Enter both the address and the port.")
        updates["luxtronik_host"] = validate_host(body.luxtronik_host)
        updates["luxtronik_port"] = validate_port(body.luxtronik_port)
    for name, label in (
        ("pump_maker", "Pump maker"),
        ("pump_model", "Pump model"),
        ("controller_model", "Controller model"),
        ("controller_software", "Software version"),
    ):
        if name in sent:
            updates[name] = _optional_text(getattr(body, name), label)
    if {"ai_provider", "ai_model", "advice_prompt", "settings_prompt"} & sent:
        provider = validate_provider(body.ai_provider)
        updates["ai_provider"] = provider
        updates["ai_model"] = validate_model(provider, body.ai_model)
        updates["advice_prompt"] = validate_prompt(body.advice_prompt, "advice prompt")
        updates["settings_prompt"] = validate_prompt(body.settings_prompt, "settings prompt")
    if updates:
        apply_app_preference(session, **updates)
    return app_settings_payload(session)


def validate_host(value: str | None) -> str:
    text = (value or "").strip()
    if not text or len(text) > 255 or any(character.isspace() for character in text):
        raise PreferenceError("Enter the heat pump address without spaces.")
    return text


def validate_port(value) -> int:
    if isinstance(value, bool):
        raise PreferenceError("Enter a port from 1 to 65535.")
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise PreferenceError("Enter a port from 1 to 65535.") from exc
    if port < 1 or port > 65535:
        raise PreferenceError("Enter a port from 1 to 65535.")
    return port


def _optional_text(value: str | None, label: str) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    if len(text) > IDENTITY_LIMIT:
        raise PreferenceError(f"{label} must be at most {IDENTITY_LIMIT} characters.")
    return text


def _stored(row, name: str) -> str | None:
    if row is None:
        return None
    value = getattr(row, name, None)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _from_row(row, settings: Settings) -> Runtime:
    provider = _stored(row, "ai_provider") or settings.ai_provider
    try:
        provider = validate_provider(provider)
    except AdvisorError:
        provider = "openai"
    model = _stored(row, "ai_model") or settings.ai_model.strip()
    if model not in MODEL_CHOICES[provider]:
        model = DEFAULT_MODELS[provider]
    port = settings.luxtronik_port
    if row is not None and row.luxtronik_port:
        try:
            port = validate_port(row.luxtronik_port)
        except PreferenceError:
            port = settings.luxtronik_port
    return Runtime(
        settings=settings,
        host=_stored(row, "luxtronik_host") or settings.luxtronik_host,
        port=port,
        provider=provider,
        model=model,
        advice_prompt=_stored(row, "advice_prompt") or SYSTEM_PROMPT,
        settings_prompt=_stored(row, "settings_prompt") or SETTINGS_PROMPT,
        pump_maker=_stored(row, "pump_maker") or "",
        pump_model=_stored(row, "pump_model") or "",
        controller_model=_stored(row, "controller_model") or "",
        controller_software=_stored(row, "controller_software") or "",
    )
