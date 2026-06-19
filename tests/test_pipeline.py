"""Tests for forza.pipeline.

Raw model evidence is SQL-first. The pipeline preserves raw response text and
parsed payloads in ExtractionResult and only propagates an artifact path when a
backend explicitly returns one.
"""

import json
from pathlib import Path

from forza.config import load_config
from forza.domain.normalizer import ReferenceData
from forza.lmstudio import ModelExtractionResult
from forza.pipeline.image import EncodedImage
from forza.pipeline.process import process_image


class FakeBackend:
    """Minimal LLM backend stub.

    Records the arguments received by ``extract`` so individual tests can
    inspect them without imposing constraints on other tests.
    Assertions about specific argument values belong in the test, not here.
    """

    def __init__(self, raw, raw_response_artifact_path=None):
        self.raw = raw
        self.raw_response_artifact_path = raw_response_artifact_path
        self.last_image_b64: str | None = None
        self.last_mime: str | None = None
        self.last_semantic_name: str | None = None
        self.last_run_id: str | None = None
        self.last_file_hash: str | None = None

    def extract(self, image_b64, mime, semantic_name, run_id, file_hash):
        self.last_image_b64 = image_b64
        self.last_mime = mime
        self.last_semantic_name = semantic_name
        self.last_run_id = run_id
        self.last_file_hash = file_hash
        return ModelExtractionResult(parsed=self.raw, raw_response=json.dumps(self.raw), raw_response_artifact_path=self.raw_response_artifact_path)



def encoded_payload(
    data_b64: str = "encoded",
    mime_type: str = "image/png",
    *,
    fmt: str = "png",
    width_px: int = 1,
    height_px: int = 1,
    byte_count: int = 7,
) -> EncodedImage:
    return EncodedImage(
        data_b64=data_b64,
        mime_type=mime_type,
        format=fmt,
        width_px=width_px,
        height_px=height_px,
        byte_count=byte_count,
    )

def refs_from(tracks):
    return ReferenceData(tracks=tracks, cars=[], car_map={})


def base_raw(track):
    return {
        "t": track,
        "tf": 76,
        "w": "dry",
        "e": [
            {
                "dr": "Bujica89",
                "ca": "Mazda MX-5 '90",
                "cl": "500 D",
                "bl": "00:56.092",
            }
        ],
    }


def test_empty_track_becomes_unknown_not_ambiguous(tmp_path, monkeypatch):
    from forza import pipeline

    monkeypatch.setattr("forza.pipeline.process.encode_image_payload", lambda *a, **kw: encoded_payload())
    cfg = load_config(tmp_path / "missing.ini")
    image = tmp_path / "input.png"
    image.write_text("not really an image")
    backend = FakeBackend(base_raw(""))

    result = process_image(
        image.name,
        "hash",
        image,
        backend,
        refs_from(["Brands Hatch Grand Prix Circuit", "Brands Hatch Indy Circuit"]),
        cfg,
        "run",
    )

    assert backend.last_image_b64 == "encoded"
    assert backend.last_mime == "image/png"
    assert backend.last_file_hash == "hash"
    assert backend.last_run_id == "run"
    assert result.status == "ok"
    assert result.session.track == "Unknown"


def test_nonempty_ambiguous_track_still_flags_for_review(tmp_path, monkeypatch):
    from forza import pipeline

    monkeypatch.setattr("forza.pipeline.process.encode_image_payload", lambda *a, **kw: encoded_payload())
    cfg = load_config(tmp_path / "missing.ini")
    image = tmp_path / "input.png"
    image.write_text("not really an image")

    result = process_image(
        image.name,
        "hash",
        image,
        FakeBackend(base_raw("Brands Hatch")),
        refs_from(["Brands Hatch Grand Prix Circuit", "Brands Hatch Indy Circuit"]),
        cfg,
        "run",
    )

    assert result.status == "ok"
    assert result.session.track == "Unknown (ambiguous layout): Brands Hatch"


def test_process_image_ignores_out_of_range_fahrenheit_consistently(tmp_path, monkeypatch):
    from forza import pipeline

    monkeypatch.setattr("forza.pipeline.process.encode_image_payload", lambda *a, **kw: encoded_payload())
    cfg = load_config(tmp_path / "missing.ini")
    image = tmp_path / "input.png"
    image.write_text("not really an image")
    raw = base_raw("Lime Rock Park Full Circuit")
    raw["tf"] = 200

    result = process_image(
        image.name,
        "hash",
        image,
        FakeBackend(raw),
        refs_from(["Lime Rock Park Full Circuit"]),
        cfg,
        "run",
    )

    assert result.status == "ok"
    assert result.session.temp_f is None
    assert result.session.temp_c is None


def test_process_image_keeps_valid_fahrenheit_and_celsius(tmp_path, monkeypatch):
    from forza import pipeline

    monkeypatch.setattr("forza.pipeline.process.encode_image_payload", lambda *a, **kw: encoded_payload())
    cfg = load_config(tmp_path / "missing.ini")
    image = tmp_path / "input.png"
    image.write_text("not really an image")
    raw = base_raw("Lime Rock Park Full Circuit")
    raw["tf"] = 86

    result = process_image(
        image.name,
        "hash",
        image,
        FakeBackend(raw),
        refs_from(["Lime Rock Park Full Circuit"]),
        cfg,
        "run",
    )

    assert result.status == "ok"
    assert result.session.temp_f == 86.0
    assert result.session.temp_c == 30.0


def test_process_image_keeps_raw_response_in_sql_contract_without_fabricating_artifact_path(tmp_path, monkeypatch):
    monkeypatch.setattr("forza.pipeline.process.encode_image_payload", lambda *a, **kw: encoded_payload())
    cfg = load_config(tmp_path / "missing.ini")
    image = tmp_path / "input.png"
    image.write_text("not really an image")

    backend = FakeBackend(base_raw("Lime Rock Park Full Circuit"))

    result = process_image(
        image.name,
        "abcdef1234567890ffff",
        image,
        backend,
        refs_from(["Lime Rock Park Full Circuit"]),
        cfg,
        "run",
    )

    assert backend.last_file_hash == "abcdef1234567890ffff"
    assert result.status == "ok"
    assert result.raw_response
    assert result.raw_response_payload is not None
    assert result.raw_response_payload["t"] == "Lime Rock Park Full Circuit"
    assert result.raw_response_artifact_path is None



def test_process_image_preserves_backend_registered_raw_artifact_path(tmp_path, monkeypatch):
    monkeypatch.setattr("forza.pipeline.process.encode_image_payload", lambda *a, **kw: encoded_payload())
    cfg = load_config(tmp_path / "missing.ini")
    image = tmp_path / "Screenshot_2024_01_15.png"
    image.write_text("not really an image")

    artifact_path = tmp_path / "explicit-artifact.json"
    backend = FakeBackend(
        base_raw("Mugello Circuit Full Circuit"),
        raw_response_artifact_path=str(artifact_path),
    )

    result = process_image(
        image.name,
        "deadbeef00112233aabb",
        image,
        backend,
        refs_from(["Mugello Circuit Full Circuit"]),
        cfg,
        "myrun",
    )

    assert result.status == "ok"
    assert result.raw_response_artifact_path == str(artifact_path)

