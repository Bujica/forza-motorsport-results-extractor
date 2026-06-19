import pytest
from pathlib import Path
from forza.domain.normalizer import (
    load_reference_seed_text_data, fix_track_name, fix_car_name,
    ReferenceData, _track_key, _normalise,
)


# ─────────────────────── helpers ────────────────────────────────────────────

def refs_from(tracks: list[str], cars: list[str]) -> ReferenceData:
    from forza.domain.normalizer import _build_car_map
    return ReferenceData(tracks=tracks, cars=cars, car_map=_build_car_map(cars))


TRACKS = [
    "Lime Rock Park Full Circuit",
    "Brands Hatch Grand Prix Circuit",
    "Brands Hatch Indy Circuit",
    "Le Mans - Circuit International de la Sarthe Full Circuit",
    "Le Mans - Circuit International de la Sarthe Old Mulsanne Circuit",
    "Nurburgring Nordschleife",
    "Silverstone Racing Circuit Grand Prix Circuit",
    "Road America Full Circuit",
    "Hakone Grand Prix Circuit",
    "Eaglerock Speedway Club Circuit",
    "Eaglerock Speedway Club Circuit Reverse",
]

CARS = [
    "Mazda MX-5 '90",
    "Mazda MX-5 Miata '94",
    "Porsche 550 S '55",
    "Ferrari 308 GTS '77",
    "Honda Civic Type R '97",
    "Ford Escort RS Cosworth '92",
    "Renault 5 Turbo '80",
]


# ─────────────────────── load_reference_seed_text_data ────────────────────────────────

class TestLoadReferenceData:
    def test_loads_tracks_from_file(self, tmp_path):
        f = tmp_path / "tracks.txt"
        f.write_text("Track A\nTrack B\n\nTrack C\n", encoding="utf-8")
        refs = load_reference_seed_text_data(f, tmp_path / "cars.txt")
        assert refs.tracks == ["Track A", "Track B", "Track C"]

    def test_loads_cars_from_file(self, tmp_path):
        f = tmp_path / "cars.txt"
        f.write_text("Car A\nCar B\n", encoding="utf-8")
        refs = load_reference_seed_text_data(tmp_path / "tracks.txt", f)
        assert refs.cars == ["Car A", "Car B"]

    def test_missing_tracks_file_returns_empty(self, tmp_path):
        refs = load_reference_seed_text_data(tmp_path / "nope.txt", tmp_path / "cars.txt")
        assert refs.tracks == []

    def test_missing_cars_file_returns_empty(self, tmp_path):
        refs = load_reference_seed_text_data(tmp_path / "tracks.txt", tmp_path / "nope.txt")
        assert refs.cars == []

    def test_blank_lines_stripped(self, tmp_path):
        f = tmp_path / "tracks.txt"
        f.write_text("\n  \nTrack A\n  Track B  \n\n", encoding="utf-8")
        refs = load_reference_seed_text_data(f, tmp_path / "cars.txt")
        assert refs.tracks == ["Track A", "Track B"]

    def test_car_map_built(self, tmp_path):
        f = tmp_path / "cars.txt"
        f.write_text("Mazda MX-5 '90\nFerrari 308 GTS '77\n", encoding="utf-8")
        refs = load_reference_seed_text_data(tmp_path / "tracks.txt", f)
        assert len(refs.car_map) == 2

    def test_car_map_no_duplicates_first_wins(self, tmp_path):
        f = tmp_path / "cars.txt"
        f.write_text("Mazda MX5\nMazda MX5\n", encoding="utf-8")
        refs = load_reference_seed_text_data(tmp_path / "tracks.txt", f)
        assert len(refs.car_map) == 1


# ─────────────────────── fix_track_name ─────────────────────────────────────

class TestFixTrackName:
    def test_empty_string_unchanged(self):
        refs = refs_from(TRACKS, [])
        assert fix_track_name("", refs) == ""

    def test_no_tracks_ref_returns_raw(self):
        refs = refs_from([], [])
        assert fix_track_name("SomeTrack", refs) == "SomeTrack"

    def test_exact_match_case_insensitive(self):
        refs = refs_from(TRACKS, [])
        assert fix_track_name("lime rock park full circuit", refs) == \
               "Lime Rock Park Full Circuit"

    def test_exact_match_preserves_canonical_case(self):
        refs = refs_from(TRACKS, [])
        assert fix_track_name("BRANDS HATCH GRAND PRIX CIRCUIT", refs) == \
               "Brands Hatch Grand Prix Circuit"

    def test_accent_normalised_match(self):
        refs = refs_from(TRACKS, [])
        result = fix_track_name("nurburgring nordschleife", refs)
        assert result == "Nurburgring Nordschleife"

    def test_punctuation_insensitive_match(self):
        refs = refs_from(TRACKS, [])
        raw = "Le Mans Circuit International de la Sarthe Full Circuit"
        assert fix_track_name(raw, refs) == \
               "Le Mans - Circuit International de la Sarthe Full Circuit"

    def test_fuzzy_match_close_enough(self):
        refs = refs_from(TRACKS, [])
        raw = "Silverstone Racng Circuit Grand Prix Circuit"
        result = fix_track_name(raw, refs)
        assert result == "Silverstone Racing Circuit Grand Prix Circuit"

    def test_ambiguous_prefix_returns_track_ambiguous(self):
        """
        Le Mans base name matches both Full Circuit and Old Mulsanne Circuit.
        The normalizer must return None instead of guessing.
        """
        refs = refs_from(TRACKS, [])
        result = fix_track_name(
            "Le Mans - Circuit International de la Sarthe", refs
        )
        assert result is None

    def test_ambiguous_prefix_does_not_resolve_to_full_circuit(self):
        """Regression: old behaviour would fuzzy-match to Full Circuit."""
        refs = refs_from(TRACKS, [])
        result = fix_track_name(
            "Le Mans - Circuit International de la Sarthe", refs
        )
        assert result is None

    def test_unambiguous_prefix_still_resolves(self):
        """Nurburgring is unambiguous — prefix match should still work."""
        refs = refs_from(TRACKS, [])
        result = fix_track_name("Nurburgring Nord", refs)
        assert result == "Nurburgring Nordschleife"

    def test_brands_hatch_base_ambiguous(self):
        """'Brands Hatch' alone matches both Grand Prix and Indy — must not guess."""
        refs = refs_from(TRACKS, [])
        result = fix_track_name("Brands Hatch", refs)
        assert result is None

    def test_brands_hatch_indy_unambiguous(self):
        refs = refs_from(TRACKS, [])
        assert fix_track_name("Brands Hatch Indy Circuit", refs) == \
               "Brands Hatch Indy Circuit"

    def test_unknown_track_returned_unchanged(self):
        refs = refs_from(TRACKS, [])
        assert fix_track_name("Fictional Raceway North Loop", refs) == \
               "Fictional Raceway North Loop"

    def test_eaglerock_reverse_distinguished_from_forward(self):
        refs = refs_from(TRACKS, [])
        assert fix_track_name("Eaglerock Speedway Club Circuit Reverse", refs) == \
               "Eaglerock Speedway Club Circuit Reverse"
        assert fix_track_name("Eaglerock Speedway Club Circuit", refs) == \
               "Eaglerock Speedway Club Circuit"

    def test_extra_whitespace_trimmed(self):
        refs = refs_from(TRACKS, [])
        assert fix_track_name("  Road America Full Circuit  ", refs) == \
               "Road America Full Circuit"

    def test_le_mans_full_circuit_with_layout_resolves(self):
        """When the full name including layout is given, it must resolve correctly."""
        refs = refs_from(TRACKS, [])
        assert fix_track_name(
            "Le Mans - Circuit International de la Sarthe Full Circuit", refs
        ) == "Le Mans - Circuit International de la Sarthe Full Circuit"

    def test_le_mans_old_mulsanne_with_layout_resolves(self):
        refs = refs_from(TRACKS, [])
        assert fix_track_name(
            "Le Mans - Circuit International de la Sarthe Old Mulsanne Circuit", refs
        ) == "Le Mans - Circuit International de la Sarthe Old Mulsanne Circuit"


# ─────────────────────── fix_car_name ───────────────────────────────────────

class TestFixCarName:
    def test_empty_string_unchanged(self):
        refs = refs_from([], CARS)
        assert fix_car_name("", refs) == ""

    def test_no_cars_ref_returns_raw(self):
        refs = refs_from([], [])
        assert fix_car_name("Mazda MX-5 '90", refs) == "Mazda MX-5 '90"

    def test_exact_match_returns_canonical(self):
        refs = refs_from([], CARS)
        assert fix_car_name("Mazda MX-5 '90", refs) == "Mazda MX-5 '90"

    def test_normalised_exact_match(self):
        refs = refs_from([], CARS)
        result = fix_car_name("Mazda MX5 90", refs)
        assert result == "Mazda MX-5 '90"

    def test_fuzzy_match_minor_typo(self):
        refs = refs_from([], CARS)
        result = fix_car_name("Mazda MX-5 Miata 1994", refs)
        assert result == "Mazda MX-5 Miata '94"

    def test_no_match_returns_original(self):
        refs = refs_from([], CARS)
        original = "XYZ Completely Unknown Car"
        assert fix_car_name(original, refs) == original

    def test_short_abbreviation_no_false_positive(self):
        refs = refs_from([], CARS)
        assert fix_car_name("XYZ", refs) == "XYZ"


# ─────────────────────── internal helpers ───────────────────────────────────

class TestNormalizeHelpers:
    def test_normalise_strips_accents(self):
        assert _normalise("Nurburgring") == "nurburgring"

    def test_normalise_lowercases(self):
        assert _normalise("BRANDS HATCH") == "brands hatch"

    def test_normalise_no_spaces_removes_non_alnum(self):
        assert _normalise("MX-5 '90", spaces=False) == "mx590"

    def test_track_key_collapses_punctuation(self):
        assert _track_key("Le Mans - Circuit") == "le mans circuit"

    def test_track_key_accent_stripped(self):
        assert _track_key("Nurburgring") == "nurburgring"

    def test_track_ambiguous_is_empty_string(self):
        assert fix_track_name("Eaglerock Speedway", refs_from(TRACKS, [])) is None

