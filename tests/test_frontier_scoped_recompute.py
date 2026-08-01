"""Equivalence tests for scoped best-lap recompute (B-5).

These tests prove the premise the B-5 fix depends on: restricting the input
rows to a set of ``(track, race_class)`` groups before running
``FrontierCalculator`` produces exactly the same winners, for those groups,
as running the calculator over the entire dataset and then filtering the
result down to the same groups.

This holds because every grouping key inside ``FrontierCalculator`` — in both
``clean_frontier_rows`` (player_by_car, player_overall, opponent_best) and
``simple_best_rows`` — starts with ``(track, race_class, ...)``. Neither
method ever compares rows across different ``(track, race_class)`` pairs, so
narrowing the input to only the affected groups cannot change the outcome
for rows inside those groups.

Deliberately excludes ``weather`` from the scope key even though
``clean_frontier_rows`` sub-groups by it: ``simple_best_rows`` (the
no-gamertag fallback) does not include weather in its own grouping key, so a
scope tighter than ``(track, race_class)`` would be unsafe for that mode.
"""

from __future__ import annotations

from dataclasses import dataclass

from forza.db.repositories.frontier import FrontierCalculator

GAMERTAG = "Bujica89"


@dataclass
class _Lap:
    id: str
    image_file_id: str
    track: str
    race_class: str
    weather: str | None
    temp_f: float | None
    driver: str
    car: str
    best_lap_ms: int
    dirty: bool = False


def _rows() -> list[_Lap]:
    """Two unrelated (track, race_class) groups, each with player + opponents,
    plus a second weather condition inside one group and a dirty row to
    exercise the branches that matter for the equivalence claim."""
    return [
        # Group A: (Silverstone, A) — player has two cars, one opponent beats them.
        _Lap("a1", "img-a1", "Silverstone", "A", "dry", 75.0, GAMERTAG, "Car1", 90000),
        _Lap("a2", "img-a2", "Silverstone", "A", "dry", 75.0, GAMERTAG, "Car2", 91000),
        _Lap("a3", "img-a3", "Silverstone", "A", "dry", 75.0, "Rival", "Car1", 88000),
        _Lap("a4", "img-a4", "Silverstone", "A", "dry", 75.0, "TooSlow", "Car1", 95000),
        # Same group, different weather — must be visible to a (track, race_class) scope.
        _Lap("a5", "img-a5", "Silverstone", "A", "wet", 60.0, GAMERTAG, "Car1", 100000),
        _Lap("a6", "img-a6", "Silverstone", "A", "wet", 60.0, "Rival", "Car1", 99000),
        # A dirty row that must never win either mode.
        _Lap("a7", "img-a7", "Silverstone", "A", "dry", 75.0, GAMERTAG, "Car1", 80000, dirty=True),
        # Group B: (Mugello, B) — completely unrelated group, must not affect group A.
        _Lap("b1", "img-b1", "Mugello", "B", "dry", 80.0, GAMERTAG, "CarX", 70000),
        _Lap("b2", "img-b2", "Mugello", "B", "dry", 80.0, "Opponent", "CarX", 71000),
        _Lap("b3", "img-b3", "Mugello", "B", "dry", 80.0, "Opponent", "CarY", 69000),
    ]


def test_clean_frontier_rows_scoped_by_group_matches_full_computation_filtered():
    all_rows = _rows()
    calculator = FrontierCalculator()

    full_winners = calculator.clean_frontier_rows(all_rows, GAMERTAG)
    full_winner_ids_in_group_a = {
        row.id for row in full_winners if (row.track, row.race_class) == ("Silverstone", "A")
    }

    group_a_rows = [row for row in all_rows if (row.track, row.race_class) == ("Silverstone", "A")]
    scoped_winners = calculator.clean_frontier_rows(group_a_rows, GAMERTAG)
    scoped_winner_ids = {row.id for row in scoped_winners}

    assert scoped_winner_ids == full_winner_ids_in_group_a
    # Sanity: the clearly-too-slow opponent never wins.
    assert "a4" not in scoped_winner_ids


def test_simple_best_rows_scoped_by_group_matches_full_computation_filtered():
    all_rows = _rows()
    calculator = FrontierCalculator()

    full_winners = calculator.simple_best_rows(all_rows)
    full_winner_ids_in_group_a = {
        row.id for row in full_winners if (row.track, row.race_class) == ("Silverstone", "A")
    }

    group_a_rows = [row for row in all_rows if (row.track, row.race_class) == ("Silverstone", "A")]
    scoped_winners = calculator.simple_best_rows(group_a_rows)
    scoped_winner_ids = {row.id for row in scoped_winners}

    assert scoped_winner_ids == full_winner_ids_in_group_a
    assert "a7" not in scoped_winner_ids


def test_unrelated_group_never_influences_scoped_result():
    """Rows from group B must not change group A's winners, in either mode."""
    all_rows = _rows()
    calculator = FrontierCalculator()

    group_a_only = [row for row in all_rows if (row.track, row.race_class) == ("Silverstone", "A")]

    winners_with_b = {row.id for row in calculator.clean_frontier_rows(all_rows, GAMERTAG) if row.track == "Silverstone"}
    winners_without_b = {row.id for row in calculator.clean_frontier_rows(group_a_only, GAMERTAG)}
    assert winners_with_b == winners_without_b

    simple_with_b = {row.id for row in calculator.simple_best_rows(all_rows) if row.track == "Silverstone"}
    simple_without_b = {row.id for row in calculator.simple_best_rows(group_a_only)}
    assert simple_with_b == simple_without_b
