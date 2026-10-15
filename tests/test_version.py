"""The README and changelog must report the same version as app/VERSION."""

from pathlib import Path

from app.version import APP_VERSION, VERSION_FILE

ROOT = Path(__file__).resolve().parents[1]


def changelog_notes(version: str) -> str:
    """Return the body under the heading for this version."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    marker = f"## {version}\n"
    start = text.find(marker)
    if start < 0:
        raise AssertionError(f"CHANGELOG.md has no section for {version}")
    rest = text[start + len(marker) :]
    next_heading = rest.find("\n## ")
    body = rest if next_heading < 0 else rest[:next_heading]
    return body.strip()


def test_readme_reports_the_app_version():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"Version {APP_VERSION}" in readme
    assert VERSION_FILE.read_text(encoding="utf-8").strip() == APP_VERSION


def test_changelog_has_notes_for_the_app_version():
    assert changelog_notes(APP_VERSION)
