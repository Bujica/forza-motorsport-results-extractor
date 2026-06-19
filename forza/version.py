from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .app_info import APP_BASE_VERSION, APP_NAME, APP_PACKAGE_NAME


APP_DISPLAY_NAME = APP_NAME
_FALLBACK_VERSION = APP_BASE_VERSION


def _source_version() -> str | None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    if not pyproject.exists():
        return None
    in_project = False
    for line in pyproject.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "[project]":
            in_project = True
            continue
        if in_project and stripped.startswith("["):
            return None
        if in_project and stripped.startswith("version"):
            _key, _sep, value = stripped.partition("=")
            return value.strip().strip('"')
    return None


def _package_version() -> str:
    source = _source_version()
    if source:
        return source
    try:
        return version(APP_PACKAGE_NAME)
    except PackageNotFoundError:
        return _FALLBACK_VERSION


__version__ = _package_version()
APP_DISPLAY_VERSION = f"{APP_DISPLAY_NAME} {__version__}"
