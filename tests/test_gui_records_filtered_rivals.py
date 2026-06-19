from __future__ import annotations

from types import SimpleNamespace

from forza.gui.views.records_view import _filtered_records, _rivals_from_records


def _record(
    track: str,
    race_class: str,
    driver: str,
    *,
    weather: str = "dry",
    my_ms: int = 60_000,
    rival_ms: int = 59_000,
):
    return SimpleNamespace(
        track=track,
        race_class=race_class,
        weather=weather,
        rival_best_driver=driver,
        rival_best_ms=rival_ms,
        my_best_ms=my_ms,
        gap_to_rival_ms=my_ms - rival_ms,
    )


def test_records_rivals_recalculate_from_active_filters() -> None:
    records = [
        _record("Track 1", "TCR", "TCR Rival"),
        _record("Track 2", "TCR", "TCR Rival", my_ms=61_000, rival_ms=60_000),
        _record("Track 3", "S", "S Rival", my_ms=50_000, rival_ms=51_000),
    ]

    filtered = _filtered_records(records, race_class="TCR")
    rivals = _rivals_from_records(filtered)

    assert [row.driver for row in rivals] == ["TCR Rival"]
    assert rivals[0].sessions_shared == 2
    assert rivals[0].tracks_shared == ["Track 1", "Track 2"]
    assert rivals[0].their_best_ms == 59_000
    assert rivals[0].my_best_in_common_ms == 60_000
    assert rivals[0].usually_faster is True


def test_records_rivals_empty_when_filtered_records_have_no_rival() -> None:
    record = SimpleNamespace(
        track="Track",
        race_class="A",
        weather="dry",
        rival_best_driver=None,
        rival_best_ms=None,
        my_best_ms=60_000,
        gap_to_rival_ms=None,
    )

    assert _rivals_from_records([record]) == []
