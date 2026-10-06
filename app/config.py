"""Environment configuration for the local advisor."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """Runtime settings loaded from the environment and an optional .env file."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        extra="ignore",
    )

    luxtronik_host: str = "192.168.1.30"
    luxtronik_port: int = Field(default=8888, ge=1, le=65535)
    luxtronik_user_password: str = ""
    luxtronik_expert_password: str = ""
    poll_interval_seconds: int = Field(default=60, ge=5)
    database_url: str = "sqlite:///data/luxtronik_data.db"
    demo_mode: bool = False
    ai_provider: str = "openai"
    ai_model: str = ""
    advice_window_hours: int = Field(default=24, ge=1, le=168)
    short_cycle_seconds: int = Field(default=600, ge=60)
    openai_api_key: str = ""
    gemini_api_key: str = ""
    anthropic_api_key: str = ""


def get_settings() -> Settings:
    """Read .env on each call so an interval edit applies without a restart."""
    return Settings()


def resolved_database_url(url: str | None = None) -> str:
    """Turn a relative sqlite path into an absolute URL under the project root."""
    database_url = url if url is not None else get_settings().database_url
    prefix = "sqlite:///"
    if not database_url.startswith(prefix) or database_url.startswith("sqlite:////"):
        return database_url
    relative = database_url[len(prefix) :]
    path = Path(relative)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return prefix + path.as_posix()
