from __future__ import annotations

import logging
import re
from pathlib import Path
import unicodedata
from typing import Any


def load_nonempty_lines(
    path: Path | str,
    *,
    warn_missing: bool = False,
    logger: logging.Logger | None = None,
) -> list[str]:
    """Read UTF-8 text lines, trimming whitespace and dropping empty lines."""

    source = Path(path)
    if not source.exists():
        if warn_missing and logger is not None:
            logger.warning(f"Reference file not found: {source}")
        return []
    return [
        line.strip()
        for line in source.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def normalize_whitespace_lower(value: Any) -> str:
    """Collapse whitespace, trim, and lowercase for simple comparisons."""

    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def normalize_ascii_compare(value: Any, *, spaces: bool = True) -> str:
    """Normalize text for calibration comparisons.

    This preserves the previous calibration behavior: NFKD decomposition,
    combining-mark removal, lowercase, trim, and optional non-word removal.
    """

    nfkd = unicodedata.normalize("NFKD", str(value))
    text = "".join(char for char in nfkd if not unicodedata.combining(char)).lower().strip()
    return text if spaces else re.sub(r"\W+", "", text)


def strip_dirty_lap_marker(value: Any) -> str:
    """Remove trailing dirty-lap marker glyphs from a lap-time string."""

    text = re.sub(r"[\uFE00-\uFE0F]", "", str(value or "").strip())
    return re.sub(r"[▲⚠!△]+\s*$", "", text).strip()
