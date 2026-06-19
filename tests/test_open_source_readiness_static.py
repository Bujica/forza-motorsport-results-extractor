from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_open_source_baseline_files_exist() -> None:
    required = [
        "README.md",
        "LICENSE",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "CODE_OF_CONDUCT.md",
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/feature_request.yml",
        ".github/pull_request_template.md",
        ".github/workflows/ci.yml",
    ]
    missing = [path for path in required if not (ROOT / path).exists()]
    assert missing == []


def test_public_readme_contains_beta_and_disclaimer() -> None:
    text = _read("README.md")
    assert "public beta" in text.lower()
    assert "LM Studio" in text
    assert "not affiliated" in text.lower()
    assert "QUICK_GUIDE.md" in text


def test_license_matches_project_metadata() -> None:
    license_text = _read("LICENSE")
    pyproject = _read("pyproject.toml")
    assert license_text.startswith("MIT License")
    assert 'license = { text = "MIT" }' in pyproject
    assert 'readme = "README.md"' in pyproject


def test_beta_distribution_policy_excludes_development_tools() -> None:
    readme = _read("README.md")
    contributing = _read("CONTRIBUTING.md")
    security = _read("SECURITY.md")
    combined = "\n".join([readme, contributing, security])
    for token in ("tools/", "scripts/", "tests/", ".git/", ".github/"):
        assert token in combined
    assert "must not be copied into beta application bundles" in readme


def test_github_ci_uses_windows_and_project_validation() -> None:
    workflow = _read(".github/workflows/ci.yml")
    assert "windows-latest" in workflow
    assert 'python -m pip install -e \".[dev,gui]\"' in workflow
    assert "python -m compileall -q forza" in workflow
    assert "pytest" in workflow
