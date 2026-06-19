from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_request_hash(
    *,
    request_messages_json: Any,
    request_config_json: Any,
    prompt_snapshot_id: str | None,
    model: str | None,
    source_file_hash: str | None,
    request_image_format: str | None,
    request_image_mime_type: str | None,
    request_image_width: int | None,
    request_image_height: int | None,
    request_image_bytes: int | None,
) -> str:
    """Hash the exact redacted request evidence persisted in SQLite."""
    canonical = {
        "request_messages_json": request_messages_json,
        "request_config_json": request_config_json,
        "prompt_snapshot_id": prompt_snapshot_id,
        "model": model,
        "source_file_hash": source_file_hash,
        "request_image_format": request_image_format,
        "request_image_mime_type": request_image_mime_type,
        "request_image_width": request_image_width,
        "request_image_height": request_image_height,
        "request_image_bytes": request_image_bytes,
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
