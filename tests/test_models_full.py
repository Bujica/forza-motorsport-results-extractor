import pytest
from pydantic_core import ValidationError
from forza.schemas import (
    LapRecord, RaceSession, ExtractionResult,
    dump_schema, validate_schema,
)


# ─────────────────────── helpers ────────────────────────────────────────────

def make_entry(**kw) -> LapRecord:
    defaults = dict(
        driver="Bujica89", car="Mazda MX-5 '90", car_class="D",
        best_lap="00:56.092", best_lap_ms=56092, dirty=False,
    )
    return LapRecord(**{**defaults, **kw})


def make_result(**kw) -> ExtractionResult:
    e = make_entry()
    s = RaceSession("Lime Rock Park Full Circuit", 76.0, 24.4, [e], "D", "dry")
    defaults = dict(source_file="img.png", file_hash="deadbeef", session=s, status="ok")
    return ExtractionResult(**{**defaults, **kw})


def lap_to_dict(lap: LapRecord) -> dict:
    return dump_schema(lap)


def lap_from_dict(data: dict) -> LapRecord:
    return validate_schema(LapRecord, data)


def session_to_dict(session: RaceSession) -> dict:
    return dump_schema(session)


def session_from_dict(data: dict) -> RaceSession:
    return validate_schema(RaceSession, data)


def result_to_dict(result: ExtractionResult) -> dict:
    return dump_schema(result)


def result_from_dict(data: dict) -> ExtractionResult:
    return validate_schema(ExtractionResult, data)


# ─────────────────────── LapRecord round-trip ────────────────────────────────

class TestLapRecordRoundTrip:
    def test_clean_entry_round_trips(self):
        e = make_entry()
        assert lap_from_dict(lap_to_dict(e)) == e

    def test_dirty_entry_round_trips(self):
        e = make_entry(dirty=True, best_lap="00:56.092\u25b2")
        rt = lap_from_dict(lap_to_dict(e))
        assert rt.dirty is True
        assert rt.best_lap == "00:56.092\u25b2"

    def test_extra_name_fields_are_ignored(self):
        d = {
            "driver": "X", "car": "Y", "car_class": "D",
            "best_lap": "1:00.000", "best_lap_ms": 60000,
            "dirty": False,
            "driver_raw": "extra driver value",
            "car_raw": "extra car value",
        }
        e = lap_from_dict(d)
        assert not hasattr(e, "driver_raw")
        assert not hasattr(e, "car_raw")

    def test_dict_has_expected_keys(self):
        d = lap_to_dict(make_entry())
        for key in ("driver", "car", "car_class", "best_lap", "best_lap_ms",
                    "dirty"):
            assert key in d
        assert "driver_raw" not in d
        assert "car_raw" not in d

    def test_best_lap_ms_stored_as_int(self):
        d = lap_to_dict(make_entry(best_lap_ms=56092))
        assert isinstance(d["best_lap_ms"], int)

    def test_from_dict_casts_ms_to_int(self):
        e = lap_from_dict({
            "driver": "X", "car": "Y", "car_class": "D",
            "best_lap": "1:30.000", "best_lap_ms": "90000",
            "dirty": False,
        })
        assert isinstance(e.best_lap_ms, int)
        assert e.best_lap_ms == 90000

    def test_from_dict_requires_car_class(self):
        with pytest.raises(ValidationError):
            lap_from_dict({
                "driver": "X", "car": "Y",
                "best_lap": "1:30.000", "best_lap_ms": 90000,
            })

    def test_sub_minute_lap_round_trips(self):
        e = make_entry(best_lap="00:56.092", best_lap_ms=56092)
        rt = lap_from_dict(lap_to_dict(e))
        assert rt.best_lap == "00:56.092"
        assert rt.best_lap_ms == 56092


# ─────────────────────── RaceSession round-trip ──────────────────────────────

class TestRaceSessionRoundTrip:
    def test_full_session_round_trips(self):
        s = RaceSession("Lime Rock", 77.0, 25.0, [make_entry()], "D", "dry")
        rt = session_from_dict(session_to_dict(s))
        assert rt.track == "Lime Rock"
        assert rt.temp_f == pytest.approx(77.0)
        assert rt.weather == "dry"
        assert len(rt.entries) == 1

    def test_weather_defaults_to_unknown_when_missing(self):
        d = {"track": "X", "temp_f": 77, "temp_c": 25,
             "race_class": "A", "entries": []}
        s = session_from_dict(d)
        assert s.weather == "unknown"

    def test_temp_f_none_round_trips(self):
        s = RaceSession("Track", None, None, [], "A", "dry")
        rt = session_from_dict(session_to_dict(s))
        assert rt.temp_f is None
        assert rt.temp_c is None

    def test_multiple_entries_all_preserved(self):
        entries = [LapRecord(f"Driver{i}", "Car", "A", "1:30", 90.0, False)
                   for i in range(5)]
        s = RaceSession("Track", 77.0, 25.0, entries, "A", "dry")
        rt = session_from_dict(session_to_dict(s))
        assert len(rt.entries) == 5

    def test_rain_weather_preserved(self):
        s = RaceSession("Track", 70.0, 21.1, [], "B", "rain")
        rt = session_from_dict(session_to_dict(s))
        assert rt.weather == "rain"

    def test_track_is_required(self):
        with pytest.raises(ValidationError):
            session_from_dict({"temp_f": 77, "temp_c": 25,
                               "race_class": "A", "entries": []})


# ─────────────────────── ExtractionResult round-trip ───────────────────────────

class TestExtractionResultRoundTrip:
    def test_ok_result_round_trips(self):
        r  = make_result()
        rt = result_from_dict(result_to_dict(r))
        assert rt.source_file == r.source_file
        assert rt.file_hash   == r.file_hash
        assert rt.status      == "ok"

    def test_error_result_round_trips(self):
        r  = ExtractionResult("bad.png", "hbad", None, "error", error="OCR timeout")
        rt = result_from_dict(result_to_dict(r))
        assert rt.session is None
        assert rt.status  == "error"
        assert rt.error   == "OCR timeout"

    def test_result_dict_has_required_keys(self):
        d = result_to_dict(make_result())
        for key in ("source_file", "file_hash", "session", "status", "error"):
            assert key in d

    def test_result_dict_has_no_debug_fields(self):
        d = result_to_dict(make_result())
        for key in ("elapsed", "tokens_used", "pipeline_meta"):
            assert key not in d, f"Debug field '{key}' should not be in cache"

    def test_status_defaults_to_error_when_missing(self):
        r = result_from_dict({
            "source_file": "f.png", "file_hash": "h", "session": None,
        })
        assert r.status == "error"

    def test_result_with_extra_debug_fields_loads_cleanly(self):
        d = {
            "source_file": "old.png", "file_hash": "hash", "status": "ok",
            "session": {
                "track": "Track", "temp_f": 77, "temp_c": 25, "race_class": "A",
                "entries": [{
                    "driver": "Bujica89", "car": "Car", "car_class": "A",
                    "best_lap": "1:30.000", "best_lap_ms": 90000, "dirty": False,
                }],
            },
            "elapsed": 22.4,
            "tokens_used": 4438,
            "pipeline_meta": {
                "pipeline_version": "0.9.0", "backend": "lmstudio",
                "model": "qwen/qwen3.5-9b",
                "endpoint": "http://127.0.0.1:1234/v1/chat/completions",
                "max_width": 2560, "grayscale": True, "encode_quality": 100,
                "image_format": "png", "temperature": 0.0,
            },
        }
        r = result_from_dict(d)
        assert r.status == "ok"
        assert r.session is not None
        assert r.session.weather == "unknown"

    def test_weather_unknown_default_when_missing(self):
        d = {
            "source_file": "old.png", "file_hash": "hash", "status": "ok",
            "session": {
                "track": "Track", "temp_f": 77, "temp_c": 25, "race_class": "A",
                "entries": [{
                    "driver": "X", "car": "Y", "car_class": "A",
                    "best_lap": "1:30.000", "best_lap_ms": 90000, "dirty": False,
                }],
            },
        }
        r = result_from_dict(d)
        assert r.session.weather == "unknown"
        assert not hasattr(r.session.entries[0], "driver_raw")
