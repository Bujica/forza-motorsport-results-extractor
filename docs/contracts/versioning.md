# Versioning Contract

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: application version, changelog, release labeling, and validation
Last verified: 2026-06-18
Supersedes: versioning rules implied by changelog entries
Related tests: `tests/test_version.py`, `tests/test_cli.py`

The project version is an operator-facing contract. It must identify the code
being run in the GUI, CLI help, packages, release notes, and release tags.

## Source Of Truth

- `pyproject.toml` `[project].version` is the source of truth.
- `forza.version.__version__` must resolve to the local source-tree version
  during editable development.
- GUI metadata, window title, sidebar version, and status bar version must use
  `forza.version`.
- Do not hard-code independent GUI, CLI, docs, or package version strings.

## Version Bumps

- Do not bump the version for ordinary unreleased development.
- Patch versions are for compatible bug fixes, documentation-contract fixes,
  GUI usability fixes, and validation hardening after a released version.
- Minor versions are for new user-visible workflows, architecture additions, or
  database/runtime behavior that remains compatible after explicit migrations.
- Major versions are only for intentional incompatible workflow, data, CLI, or
  database-contract changes.
- If a change is shipped from a local maintenance branch, the release version
  must be decided locally before tagging or publishing. Do not infer it from a
  remote patch-status document.

## Release Checklist

Before a release tag or release PR:

1. Move `CHANGELOG.md` `Unreleased` entries into a dated version section.
2. Update `pyproject.toml` to the exact release version.
3. Confirm `forza.version.__version__` matches `pyproject.toml`.
4. Run `python -m forza --help` and confirm the displayed workflow commands are
   current.
5. Smoke-test GUI startup and confirm the displayed version is current.
6. Run the validation gates in `docs/project_status.md`.
7. Tag using the same version as `pyproject.toml`.

## Known Issues

No known versioning issues are currently approved.
