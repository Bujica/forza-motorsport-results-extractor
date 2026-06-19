from __future__ import annotations

import logging

from forza.application import external_record_service as service


def test_load_aliases_logs_missing_file(tmp_path, caplog) -> None:
    missing = tmp_path / "track_aliases.json"

    with caplog.at_level(logging.INFO, logger="forza"):
        aliases, issues = service._load_aliases(missing)

    assert aliases == {}
    assert issues == []
    assert "Track aliases file not found" in caplog.text


def test_load_aliases_logs_invalid_json(tmp_path, caplog) -> None:
    aliases_file = tmp_path / "track_aliases.json"
    aliases_file.write_text("{not-json", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="forza"):
        aliases, issues = service._load_aliases(aliases_file)

    assert aliases == {}
    assert issues == []
    assert "Invalid alias JSON" in caplog.text


def test_load_aliases_does_not_fallback_to_legacy_txt_when_json_is_missing(tmp_path, caplog) -> None:
    aliases_file = tmp_path / "track_aliases.json"
    legacy = tmp_path / "legacy_aliases.txt"
    legacy.write_text('{"Spa": "Circuit de Spa-Francorchamps Full Circuit"}', encoding="utf-8")

    with caplog.at_level(logging.INFO, logger="forza"):
        aliases, issues = service._load_aliases(aliases_file)

    assert aliases == {}
    assert issues == []
    assert "Track aliases file not found" in caplog.text
    assert "Using legacy" not in caplog.text


def test_load_aliases_reports_targets_missing_from_tracks_reference(tmp_path, caplog) -> None:
    aliases_file = tmp_path / "track_aliases.json"
    aliases_file.write_text('{"Spa": "Not A Real Track"}', encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="forza"):
        aliases, issues = service._load_aliases(
            aliases_file,
            known_tracks={"Circuit de Spa-Francorchamps Full Circuit"},
        )

    assert aliases == {}
    assert [(issue.kind, issue.value, issue.detail) for issue in issues] == [
        ("invalid_alias", "Spa", "Not A Real Track")
    ]
    assert "Alias target not found in tracks reference" in caplog.text
