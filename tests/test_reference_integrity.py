from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

from forza.domain.lap import TCR_CARS


ROOT = Path(__file__).resolve().parents[1]


def _reference_lines(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_tcr_cars_are_defined_in_cars_reference() -> None:
    cars = set(_reference_lines(ROOT / "cars.txt"))

    assert TCR_CARS <= cars


def test_canonical_ford_focus_tcr_name_is_preserved() -> None:
    """This spelling is canonical because it is present in cars.txt."""
    cars = set(_reference_lines(ROOT / "cars.txt"))

    assert "Ford #17Focus ST" in cars
    assert "Ford #17Focus ST" in TCR_CARS


def test_cars_reference_has_unique_nonblank_entries() -> None:
    cars = _reference_lines(ROOT / "cars.txt")
    duplicates = [name for name, count in Counter(cars).items() if count > 1]

    assert duplicates == []


def test_tracks_reference_has_unique_nonblank_entries() -> None:
    tracks = _reference_lines(ROOT / "tracks.txt")
    duplicates = [name for name, count in Counter(tracks).items() if count > 1]

    assert duplicates == []


def test_tracks_reference_preserves_layout_specific_names() -> None:
    tracks = set(_reference_lines(ROOT / "tracks.txt"))

    assert "Circuit de Barcelona-Catalunya National Circuit" in tracks
    assert "Circuit de Barcelona-Catalunya National Circuit ALT" in tracks
    assert "Mugello Circuit Full Circuit" in tracks
    assert "Mugello Circuit Club Circuit" in tracks


def test_external_track_alias_targets_are_canonical_reference_tracks() -> None:
    tracks = set(_reference_lines(ROOT / "tracks.txt"))
    aliases = json.loads((ROOT / "data" / "external" / "track_aliases.json").read_text(encoding="utf-8"))
    missing_targets = sorted({str(target).strip() for target in aliases.values()} - tracks)

    assert missing_targets == []

