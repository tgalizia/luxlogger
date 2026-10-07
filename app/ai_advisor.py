"""Turn measured diagnostics into a natural-language suggestion."""

import json
import logging

from app.config import Settings, get_settings
from app.settings_catalog import filter_changes

logger = logging.getLogger("luxtronik_advisor")

DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "gemini": "gemini-3.8-flash",
    "anthropic": "claude-sonnet-4-5",
}

MODEL_CHOICES = {
    "openai": ("gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"),
    "gemini": ("gemini-3.8-flash", "gemini-2.5-flash"),
    "anthropic": ("claude-sonnet-4-5", "claude-haiku-4-5"),
}

NOTE_LIMIT = 2000
PROMPT_LIMIT = 8000

SYSTEM_PROMPT = """You advise the owner of an Alpha Innotec heat pump controlled by Luxtronik 2.
You receive diagnostics computed from local measurements. Use only those figures.
The user message may name the heat pump and controller, and may include an owner note about a goal or a problem. Address that note. The only configuration to mention is heating mode, hot water mode, hot water temperature, and the heating setpoint.
Explain short cycling, compressor runtime, backup-heater use, and flow/return temperatures when the figures speak to them.
Suggest practical steps the owner can take, such as a schedule or setback change, or when to ask a technician to check flow.
Do not tell the user to write controller parameters, registers, or service-menu values. This service cannot change the heat pump.
Write plain sentences. No preamble. At most 220 words."""

SETTINGS_PROMPT = """You suggest optional changes to four household heat-pump settings.
Return only JSON: {"changes":[{"id":"...","value":...,"reason":"..."}]}
The changes list may be empty.
The user message may name the heat pump and controller, and may include an owner note about a goal or a problem. Address that note.
Leave a setting out unless the diagnostics or the owner note show a concrete reason to change it.
Do not invent a change. Prefer no change.
Never suggest Second heatsource.
Allowed settings:
- ID_Ba_Hz_akt heating mode: Automatic, Party, Holidays, or Off
- ID_Ba_Bw_akt hot water mode: Automatic, Party, Holidays, or Off
- ID_Einst_BWS_akt hot water temperature: a number from 40 to 55
- ID_Einst_WK_akt heating setpoint: a number from 15 to 35, and at most 2 degrees from the current value
Use a string for a mode and a number for a temperature. One short reason per change."""


class AdvisorError(Exception):
    """The suggestion could not be produced."""


def validate_provider(provider: str | None) -> str:
    chosen = (provider or "").strip().lower()
    if chosen not in DEFAULT_MODELS:
        raise AdvisorError("AI_PROVIDER must be openai, gemini, or anthropic.")
    return chosen


def validate_model(provider: str, model: str | None) -> str:
    """Return a model id that belongs to the provider."""
    chosen_provider = validate_provider(provider)
    chosen = (model or "").strip()
    if chosen not in MODEL_CHOICES[chosen_provider]:
        raise AdvisorError("Choose a model for the selected provider.")
    return chosen


def validate_prompt(value: str | None, label: str) -> str:
    text = (value or "").strip()
    if not text:
        raise AdvisorError(f"The {label} cannot be empty.")
    if len(text) > PROMPT_LIMIT:
        raise AdvisorError(f"The {label} must be at most {PROMPT_LIMIT} characters.")
    return text


def clean_note(value: str | None) -> str:
    text = (value or "").strip()
    if len(text) > NOTE_LIMIT:
        raise AdvisorError("Keep the note to 2000 characters.")
    return text


def context_block(identity: dict | None, note: str | None) -> str:
    """Equipment lines and the owner note. Blank values are left out."""
    identity = identity or {}
    equipment = []
    for label, key in (
        ("Pump maker", "pump_maker"),
        ("Pump model", "pump_model"),
        ("Controller", "controller_model"),
        ("Controller software", "controller_software"),
    ):
        value = str(identity.get(key) or "").strip()
        if value:
            equipment.append(f"{label}: {value}")
    parts = []
    if equipment:
        parts.append("Equipment:\n" + "\n".join(equipment))
    text = (note or "").strip()
    if text:
        parts.append("Owner note:\n" + text)
    return "\n\n".join(parts)


def with_context(body: str, identity: dict | None = None, note: str | None = None) -> str:
    extra = context_block(identity, note)
    if not extra:
        return body
    return f"{body}\n\n{extra}"


def advise(
    findings: dict,
    settings: Settings | None = None,
    *,
    identity: dict | None = None,
    note: str | None = None,
    system_prompt: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> tuple[str, str, str]:
    """Return provider, model, and suggestion text for the findings JSON."""
    settings = settings or get_settings()
    chosen_provider, chosen_model = _selection(settings, provider, model)
    api_key = _api_key(settings, chosen_provider)
    if not api_key:
        raise AdvisorError(f"Set {_key_name(chosen_provider)} in .env before asking for advice.")
    user_prompt = with_context(_diagnostics_prompt(findings), identity, clean_note(note))
    suggestion = _complete(
        chosen_provider,
        chosen_model,
        api_key,
        user_prompt,
        system_prompt or SYSTEM_PROMPT,
    )
    if not suggestion:
        raise AdvisorError("The model returned an empty suggestion.")
    return chosen_provider, chosen_model, suggestion


def suggest_settings(
    current: list[dict],
    findings: dict,
    settings: Settings | None = None,
    complete=None,
    *,
    identity: dict | None = None,
    note: str | None = None,
    system_prompt: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> list[dict]:
    """Ask the model for optional setting changes. Does not write to the controller."""
    settings = settings or get_settings()
    user_prompt = with_context(_settings_prompt(current, findings), identity, clean_note(note))
    if complete is None:
        chosen_provider, chosen_model = _selection(settings, provider, model)
        api_key = _api_key(settings, chosen_provider)
        if not api_key:
            raise AdvisorError(f"Set {_key_name(chosen_provider)} in .env before asking for a suggestion.")
        text = _complete(
            chosen_provider,
            chosen_model,
            api_key,
            user_prompt,
            system_prompt or SETTINGS_PROMPT,
        )
    else:
        text = complete(user_prompt)
    return filter_changes(_parse_changes(text), {item["id"]: item["value"] for item in current})


def _selection(settings: Settings, provider: str | None, model: str | None) -> tuple[str, str]:
    chosen_provider = validate_provider(provider or settings.ai_provider)
    chosen = (model if model is not None else settings.ai_model).strip()
    if chosen in MODEL_CHOICES[chosen_provider]:
        return chosen_provider, chosen
    return chosen_provider, DEFAULT_MODELS[chosen_provider]


def _diagnostics_prompt(findings: dict) -> str:
    return (
        "Diagnostics JSON:\n"
        + json.dumps(findings, indent=2)
        + "\n\nA short cycle is a completed compressor run shorter than "
        + f"{findings.get('short_cycle_threshold_s', 600)} seconds."
    )


def _settings_prompt(current: list[dict], findings: dict) -> str:
    return (
        "Current settings JSON:\n"
        + json.dumps(current, indent=2)
        + "\n\nDiagnostics JSON:\n"
        + json.dumps(findings, indent=2)
    )


def _parse_changes(text: str) -> list:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise AdvisorError("The model did not return setting changes.")
    try:
        payload = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AdvisorError("The model did not return setting changes.") from exc
    changes = payload.get("changes", [])
    if not isinstance(changes, list):
        raise AdvisorError("The model did not return setting changes.")
    return changes


def _api_key(settings: Settings, provider: str) -> str:
    if provider == "openai":
        return settings.openai_api_key.strip()
    if provider == "gemini":
        return settings.gemini_api_key.strip()
    return settings.anthropic_api_key.strip()


def _key_name(provider: str) -> str:
    return {
        "openai": "OPENAI_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }[provider]


def _complete(
    provider: str,
    model: str,
    api_key: str,
    user_prompt: str,
    system_prompt: str = SYSTEM_PROMPT,
) -> str:
    logger.info("Requesting advice from %s model %s", provider, model)
    if provider == "openai":
        return _openai(model, api_key, user_prompt, system_prompt)
    if provider == "gemini":
        return _gemini(model, api_key, user_prompt, system_prompt)
    return _anthropic(model, api_key, user_prompt, system_prompt)


def _openai(model: str, api_key: str, user_prompt: str, system_prompt: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=api_key, timeout=60)
    response = client.chat.completions.create(
        model=model,
        temperature=0.3,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return _text_from_openai(response)


def _gemini(model: str, api_key: str, user_prompt: str, system_prompt: str) -> str:
    from google import genai

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=user_prompt,
        config={
            "system_instruction": system_prompt,
            "temperature": 0.3,
            "automatic_function_calling": {"disable": True},
        },
    )
    return (response.text or "").strip()


def _anthropic(model: str, api_key: str, user_prompt: str, system_prompt: str) -> str:
    from anthropic import Anthropic

    client = Anthropic(api_key=api_key, timeout=60)
    response = client.messages.create(
        model=model,
        max_tokens=900,
        temperature=0.3,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    parts = []
    for block in response.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def _text_from_openai(response) -> str:
    content = response.choices[0].message.content
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            text = item.get("text") if isinstance(item, dict) else getattr(item, "text", None)
            if text:
                parts.append(text)
        return "\n".join(parts).strip()
    return str(content or "").strip()
