from __future__ import annotations

from pathlib import Path

from ..domain.normalizer import load_reference_seed_text_data
from .database_service import DatabaseService


def seed_initial_reference_text_files(database_file: Path) -> tuple[int, int]:
    """Seed initial SQL reference tables from bundled text reference data."""
    refs = load_reference_seed_text_data(Path("tracks.txt"), Path("cars.txt"))
    with DatabaseService(database_file) as database:
        return database.seed_references(tracks=refs.tracks, cars=refs.cars)

