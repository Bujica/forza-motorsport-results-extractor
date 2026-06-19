from __future__ import annotations

import base64
import hashlib
import io
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops

from ..exceptions import ImageEncodeError
from ..schemas import ImageMetadata, ModelRequestMetadata


log = logging.getLogger("forza")


# ── Supported formats ─────────────────────────────────────────────────────────

SUPPORTED_FORMATS: dict[str, str] = {
    "jpeg": "image/jpeg",
    "png":  "image/png",
    "webp": "image/webp",
}

SUPPORTED_IMAGE_EXTENSIONS: frozenset[str] = frozenset({
    ".png", ".jpg", ".jpeg", ".webp",
})


# ── Grayscale conversion ──────────────────────────────────────────────────────

def _desaturate_hsl_lightness(img: Image.Image) -> Image.Image:
    r, g, b = img.split()
    max_ch = ImageChops.lighter(ImageChops.lighter(r, g), b)
    min_ch = ImageChops.darker(ImageChops.darker(r, g), b)
    gray = Image.blend(min_ch, max_ch, 0.5)
    return Image.merge("RGB", (gray, gray, gray))


# ── Encoding ──────────────────────────────────────────────────────────────────

def encode_image(
    path: Path,
    max_width: int = 1600,
    encode_quality: int = 85,
    fmt: str = "png",
    grayscale: bool = True,
) -> tuple[str, str]:
    """Encode *path* as base64 plus MIME type.

    Encoding failures are operational errors. Returning an empty image is unsafe
    because diagnostics/pipeline callers can accidentally send an invalid
    data URL to the LLM and hide the real filesystem/image problem.
    """
    fmt = fmt.lower()
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported format '{fmt}'. Valid options: {list(SUPPORTED_FORMATS)}"
        )
    mime = SUPPORTED_FORMATS[fmt]
    try:
        with Image.open(path) as img:
            img = img.convert("RGB")
            if img.width > max_width:
                ratio = max_width / img.width
                new_h = int(img.height * ratio)
                img = img.resize((max_width, new_h), Image.Resampling.LANCZOS)
            if grayscale:
                img = _desaturate_hsl_lightness(img)
            buf = io.BytesIO()
            save_kwargs: dict = {} if fmt == "png" else {"quality": encode_quality}
            img.save(buf, format=fmt.upper(), **save_kwargs)
            return base64.b64encode(buf.getvalue()).decode(), mime
    except Exception as exc:
        log.error("[image] Failed to encode %s: %s", path, exc)
        raise ImageEncodeError(f"Failed to encode {path}: {exc}") from exc


@dataclass(frozen=True)
class EncodedImage:
    data_b64: str
    mime_type: str
    format: str
    width_px: int
    height_px: int
    byte_count: int

    def request_metadata(self, *, endpoint_url: str | None = None) -> ModelRequestMetadata:
        return ModelRequestMetadata(
            endpoint_url=endpoint_url,
            request_image_format=self.format,
            request_image_mime_type=self.mime_type,
            request_image_width_px=self.width_px,
            request_image_height_px=self.height_px,
            request_image_bytes=self.byte_count,
        )


def encode_image_payload(
    path: Path,
    max_width: int = 1600,
    encode_quality: int = 85,
    fmt: str = "png",
    grayscale: bool = True,
) -> EncodedImage:
    """Encode *path* and return transport metadata for persistence."""
    data_b64, mime = encode_image(
        path,
        max_width=max_width,
        encode_quality=encode_quality,
        fmt=fmt,
        grayscale=grayscale,
    )
    raw_bytes = base64.b64decode(data_b64)
    try:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            width, height = img.size
    except Exception as exc:
        raise ImageEncodeError(f"Failed to inspect encoded payload for {path}: {exc}") from exc
    return EncodedImage(
        data_b64=data_b64,
        mime_type=mime,
        format=fmt.lower(),
        width_px=width,
        height_px=height,
        byte_count=len(raw_bytes),
    )


def inspect_image_metadata(path: Path) -> ImageMetadata:
    """Inspect the physical source file without changing it.

    ``file_modified_at`` is the official race date source for this project.
    File creation time is intentionally not captured because Windows often
    reports the copy/import time rather than the screenshot time.
    """
    stat = path.stat()
    file_modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
    with Image.open(path) as img:
        image_format = (img.format or path.suffix.lstrip(".")).upper()
        mime_type = Image.MIME.get(img.format) if img.format else SUPPORTED_FORMATS.get(path.suffix.lstrip(".").lower())
        width_px, height_px = img.size
        color_mode = img.mode
        bit_depth = _bit_depth(img)
        raw_info = _json_safe_metadata(dict(img.info or {}))
    return ImageMetadata(
        file_size_bytes=stat.st_size,
        image_format=image_format,
        mime_type=mime_type,
        width_px=width_px,
        height_px=height_px,
        bit_depth=bit_depth,
        color_mode=color_mode,
        file_modified_at=file_modified_at,
        race_datetime=file_modified_at,
        race_date=file_modified_at.date(),
        race_datetime_source="file_modified_at",
        image_metadata_json=raw_info,
    )


def _bit_depth(img: Image.Image) -> int | None:
    bits = getattr(img, "bits", None)
    if isinstance(bits, int):
        return bits * len(img.getbands())
    mode_bits = {
        "1": 1,
        "L": 8,
        "P": 8,
        "RGB": 24,
        "RGBA": 32,
        "CMYK": 32,
        "I;16": 16,
    }
    return mode_bits.get(img.mode)


def _json_safe_metadata(raw: dict[str, Any], *, max_text: int = 500, max_items: int = 50) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for index, (key, value) in enumerate(raw.items()):
        if index >= max_items:
            safe["_truncated"] = True
            break
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[str(key)] = value[:max_text] if isinstance(value, str) else value
        elif isinstance(value, bytes):
            safe[str(key)] = f"<bytes:{len(value)}>"
        else:
            safe[str(key)] = str(value)[:max_text]
    return safe


def find_images(root: Path) -> list[Path]:
    """Return supported image files below *root*, sorted by file name."""
    if not root.exists():
        return []
    return sorted(
        [
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
        ],
        key=lambda path: path.name.lower(),
    )


def find_input_files(root: Path) -> list[Path]:
    """Return every regular file considered by a run."""
    if not root.exists():
        return []
    return sorted(
        [path for path in root.rglob("*") if path.is_file()],
        key=lambda path: path.name.lower(),
    )


# ── Hashing ───────────────────────────────────────────────────────────────────

def file_hash(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(8192):
            sha.update(chunk)
    return f"{sha.hexdigest()}_{path.stat().st_size}"


# ── File naming ───────────────────────────────────────────────────────────────

_FORBIDDEN_CHARS = '<>:"/\\|?*'


def _safe_name(text: str) -> str:
    clean = "".join(c for c in str(text) if c not in _FORBIDDEN_CHARS)
    clean = re.sub(r"[\x00-\x1f]", "", clean)
    return clean.strip().rstrip(".")[:150]


def semantic_filename(track: str, race_class: str, suffix: str = ".png") -> str:
    """Return metadata-only semantic filename text without touching the filesystem."""
    track_part = _safe_name(track) or "Unknown"
    class_part = _safe_name(race_class) or "Unknown"
    return f"{track_part} - {class_part}{suffix}"


# ── Duplicate handling ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DiscoveredImage:
    path: Path
    file_hash: str


@dataclass(frozen=True)
class DuplicateImage:
    path: Path
    file_hash: str
    reason: str
    canonical_name: str = ""
    duplicate_of_hash: str | None = None


@dataclass(frozen=True)
class ExistingImage:
    path: Path
    file_hash: str


@dataclass(frozen=True)
class SkippedImage:
    path: Path
    reason: str
    file_hash: str | None = None


@dataclass(frozen=True)
class ImageDiscoveryPlan:
    total: int
    new_images: list[DiscoveredImage]
    duplicates: list[DuplicateImage]
    existing_images: list[ExistingImage]
    skipped_images: list[SkippedImage] = field(default_factory=list)

    @property
    def duplicate_count(self) -> int:
        return len(self.duplicates)

    @property
    def process_count(self) -> int:
        return len(self.new_images)


def plan_images(
    all_images: list[Path],
    known_hashes: set[str],
    *,
    known_paths: set[str] | Mapping[str, str] | None = None,
    force: bool = False,
) -> ImageDiscoveryPlan:
    new_unique: list[DiscoveredImage] = []
    duplicates: list[DuplicateImage] = []
    existing: list[ExistingImage] = []
    skipped: list[SkippedImage] = []
    seen_in_batch: dict[str, Path] = {}
    known_paths = known_paths or set()

    for p in all_images:
        try:
            h = file_hash(p)
        except OSError:
            skipped.append(SkippedImage(p, "hash_failed"))
            continue
        known_path_hash = _known_path_hash(known_paths, str(p))
        if not force and known_path_hash == h:
            existing.append(ExistingImage(p, h))
            continue

        if not force and not isinstance(known_paths, Mapping) and str(p) in known_paths and h in known_hashes:
            existing.append(ExistingImage(p, h))
            continue

        if not force and h in known_hashes:
            duplicates.append(DuplicateImage(p, h, "cached", duplicate_of_hash=h))
            continue

        if h in seen_in_batch:
            original = seen_in_batch[h]
            duplicates.append(DuplicateImage(p, h, "batch", original.name, h))
            continue

        seen_in_batch[h] = p
        new_unique.append(DiscoveredImage(p, h))

    return ImageDiscoveryPlan(
        total=len(all_images),
        new_images=new_unique,
        duplicates=duplicates,
        existing_images=existing,
        skipped_images=skipped,
    )


def _known_path_hash(known_paths: set[str] | Mapping[str, str], path: str) -> str | None:
    if isinstance(known_paths, Mapping):
        return known_paths.get(path)
    return None


def log_duplicate_skips(plan: ImageDiscoveryPlan) -> list[Path]:
    skipped: list[Path] = []
    for duplicate in plan.duplicates:
        if duplicate.reason == "batch" and duplicate.canonical_name:
            log.info(
                f"[image] Batch duplicate, skipping in place: {duplicate.path.name} "
                f"(matches {duplicate.canonical_name})"
            )
        else:
            log.info(f"[image] Cached duplicate, skipping in place: {duplicate.path.name}")
        skipped.append(duplicate.path)
    return skipped
