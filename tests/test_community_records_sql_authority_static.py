from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


_RUNTIME_FILES = (
    "forza/config.py",
    "forza/application/config_service.py",
    "forza/application/external_record_service.py",
    "forza/gui/config_state.py",
    "forza/gui/controllers/best_laps_controller.py",
    "forza/gui/controllers/performance_controller.py",
    "forza/gui/controllers/settings_controller.py",
    "forza_config.ini.example",
    "install.py",
)


def _source(relpath: str) -> str:
    return (ROOT / relpath).read_text(encoding="utf-8")


def test_community_records_have_no_normalized_file_runtime_configuration() -> None:
    forbidden = (
        "external" + "_records_file",
        "DEFAULT" + "_RECORDS",
        "records" + "_file",
        "load_external" + "_records(",
        "records" + ".json",
    )

    for relpath in _RUNTIME_FILES:
        source = _source(relpath)
        for token in forbidden:
            assert token not in source, f"{token!r} leaked into {relpath}"


def test_track_aliases_have_no_legacy_txt_fallback_tokens() -> None:
    source = _source("forza/application/external_record_service.py")
    forbidden = (
        "track_aliases" + ".txt",
        "TRACK" + "_ALIASES",
        "Using legacy " + "track aliases",
        "Legacy " + "alias",
        "ast" + ".literal_eval",
    )

    for token in forbidden:
        assert token not in source
