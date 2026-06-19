from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_model_extraction_attempt_domain_uses_attempt_status_enum() -> None:
    domain = (ROOT / "forza" / "schemas" / "domain.py").read_text(encoding="utf-8")
    package_exports = (ROOT / "forza" / "schemas" / "__init__.py").read_text(encoding="utf-8")

    assert "AttemptStatus" in domain
    assert "status: AttemptStatus = AttemptStatus.ERROR" in domain
    assert "AttemptStatus" in package_exports
