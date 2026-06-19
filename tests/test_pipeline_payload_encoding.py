from __future__ import annotations

import base64
from pathlib import Path

from PIL import Image

from forza.pipeline.image import encode_image_payload


ROOT = Path(__file__).resolve().parents[1]
PROCESS = ROOT / "forza" / "pipeline" / "process.py"


def test_process_uses_canonical_payload_encoder() -> None:
    source = PROCESS.read_text(encoding="utf-8")

    assert "encode_image_payload(" in source
    assert "byte_count=len(data_b64)" not in source
    assert "def _encode_payload" not in source
    assert "def _image_width" not in source
    assert "def _image_height" not in source


def test_encode_image_payload_counts_encoded_bytes_and_dimensions(tmp_path: Path) -> None:
    image_path = tmp_path / "wide.png"
    Image.new("RGB", (320, 160), (12, 34, 56)).save(image_path)

    payload = encode_image_payload(
        image_path,
        max_width=80,
        encode_quality=80,
        fmt="jpeg",
        grayscale=False,
    )
    raw_bytes = base64.b64decode(payload.data_b64)

    assert payload.byte_count == len(raw_bytes)
    assert payload.byte_count != len(payload.data_b64)
    assert payload.width_px == 80
    assert payload.height_px == 40
    assert payload.format == "jpeg"
    assert payload.mime_type == "image/jpeg"
