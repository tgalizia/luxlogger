"""The version string you set in app/VERSION."""

from pathlib import Path

VERSION_FILE = Path(__file__).resolve().parent / "VERSION"


def read_version() -> str:
    """Return the version token. The file is one line, with no spaces inside it."""
    text = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not text or any(character.isspace() for character in text):
        raise RuntimeError("app/VERSION must contain a single version, such as 1.0.0.")
    return text


APP_VERSION = read_version()
