from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _class_block(source: str, class_name: str) -> str:
    start = source.index(f"class {class_name}")
    next_class = source.find("\nclass ", start + 1)
    return source[start:] if next_class == -1 else source[start:next_class]


def test_review_case_domain_uses_review_enums() -> None:
    domain = (ROOT / "forza" / "schemas" / "domain.py").read_text(encoding="utf-8")
    enums = (ROOT / "forza" / "schemas" / "enums.py").read_text(encoding="utf-8")

    assert "ReviewDecisionField" in domain
    assert "ReviewOutcome" in domain
    assert "ReviewTrigger" in domain
    assert "trigger: ReviewTrigger | None = None" in domain
    assert "outcome: ReviewOutcome = ReviewOutcome.PENDING" in domain
    assert "decision_field: ReviewDecisionField | None = None" in domain
    assert 'DRIVER_NAME = "driver_name"' in enums


def test_review_decision_field_enum_has_driver_member() -> None:
    enums = (ROOT / "forza" / "schemas" / "enums.py").read_text(encoding="utf-8")
    review_decision_field = _class_block(enums, "ReviewDecisionField")
    assert 'DRIVER = "driver"' in review_decision_field
