from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class CarCanonicalizationResult:
    original: str
    canonical: str
    key: str
    status: str

    @property
    def changed(self) -> bool:
        return self.original != self.canonical


def car_match_key(value: str | None) -> str:
    """Return a conservative matching key for Forza car names.

    The key is intended for deterministic import canonicalization, not fuzzy
    matching. It normalizes punctuation/case/year formatting variants that are
    known to split identical cars in imported external records.
    """
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = (
        text.replace("’", "'")
        .replace("‘", "'")
        .replace("`", "'")
        .replace("´", "'")
        .replace("ʹ", "'")
    )
    text = text.casefold()
    text = re.sub(r"\b(?:19|20)(\d{2})\b", r"\1", text)
    text = re.sub(r"(?<=\s)'(?=\d{2}\b)", "", text)
    text = text.replace("'", "")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(?<=[a-z])\s+(?=\d{2}\b)", "", text)
    return text


def car_canonical_map(canonical_cars: list[str] | tuple[str, ...]) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Build a unique-key map plus collision details for canonical car names."""
    by_key: dict[str, list[str]] = {}
    for name in canonical_cars:
        clean = str(name).strip()
        if not clean:
            continue
        key = car_match_key(clean)
        if not key:
            continue
        by_key.setdefault(key, [])
        if clean not in by_key[key]:
            by_key[key].append(clean)
    collisions = {key: sorted(names) for key, names in by_key.items() if len(names) > 1}
    unique = {key: names[0] for key, names in by_key.items() if len(names) == 1}
    return unique, collisions


def canonicalize_car_name(value: str, canonical_by_key: dict[str, str], collisions: dict[str, list[str]] | None = None) -> CarCanonicalizationResult:
    """Canonicalize one imported car name using exact normalized-key matching.

    Ambiguous canonical keys are deliberately not rewritten.
    """
    original = str(value or "").strip()
    key = car_match_key(original)
    if not key:
        return CarCanonicalizationResult(original=original, canonical=original, key=key, status="blank")
    if collisions and key in collisions:
        return CarCanonicalizationResult(original=original, canonical=original, key=key, status="ambiguous_car")
    canonical = canonical_by_key.get(key)
    if canonical is None:
        return CarCanonicalizationResult(original=original, canonical=original, key=key, status="new_car")
    if canonical == original:
        return CarCanonicalizationResult(original=original, canonical=canonical, key=key, status="canonical_exact")
    return CarCanonicalizationResult(original=original, canonical=canonical, key=key, status="car_alias_canonicalized")
