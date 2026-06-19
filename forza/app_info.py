from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

APP_NAME = "Forza Motorsport Results Extractor"
APP_SHORT_NAME = "FM2023 Results Extractor"
APP_PACKAGE_NAME = "forza-motorsport-results-extractor"
APP_BASE_VERSION = "0.20.0"
APP_CHANNEL = "beta"
APP_BETA_LABEL = "beta.1"
APP_RELEASE = f"{APP_BASE_VERSION}-{APP_BETA_LABEL}"
BUILD_INFO_FILENAME = "build_info.json"

TARGET_GAME = "Forza Motorsport, 2023 release"
TARGET_SCREEN = "post-race Results screen"

REPOSITORY_URL = "https://github.com/Bujica/forza-motorsport-results-extractor"
ISSUES_URL = "https://github.com/Bujica/forza-motorsport-results-extractor/issues"
LICENSE_NAME = "MIT"
MAINTAINER_NAME = "Bujica89"


def portable_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def load_build_info(root: Path | None = None) -> dict[str, Any]:
    build_info_path = (root or portable_root()) / BUILD_INFO_FILENAME
    try:
        data = json.loads(build_info_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data

APP_DESCRIPTION = (
    "Windows desktop tool for extracting lap-time data from Forza Motorsport "
    "results-screen screenshots using a local LM Studio vision model."
)
LEGAL_NOTICE = (
    "Independent community project. Not affiliated with Microsoft, Xbox, "
    "Turn 10 Studios, or the Forza Motorsport franchise."
)
