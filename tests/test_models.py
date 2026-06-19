from forza.schemas import ExtractionResult, validate_schema


def test_extraction_result_defaults_weather_and_ignores_extra_fields():
    result = validate_schema(ExtractionResult, {
        "source_file": "old.png",
        "file_hash": "hash",
        "status": "ok",
        "session": {
            "track": "Track",
            "temp_f": 77,
            "temp_c": 25,
            "race_class": "A",
            "entries": [{
                "driver": "Bujica89",
                "car": "Car",
                "car_class": "A",
                "best_lap": "1:30.000",
                "best_lap_ms": 90000,
                "dirty": False,
                "driver_raw": "extra driver value",
                "car_raw": "old raw value",
            }],
        },
    })

    assert result.session.weather == "unknown"
    assert not hasattr(result.session.entries[0], "driver_raw")
    assert not hasattr(result.session.entries[0], "car_raw")
