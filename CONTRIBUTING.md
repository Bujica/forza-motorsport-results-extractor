# Contributing

This project is preparing for a public beta. Contributions should be small, scoped, and easy to validate.

## Development setup

```bash
python install.py
pip install -e .[dev,gui]
python -m forza maintenance db-upgrade
python -m forza maintenance db-doctor --json
```

## Local validation

Run before opening a pull request:

```bash
python -m compileall -q forza
pytest
python -m forza maintenance db-doctor --json
```

For GUI changes, also smoke-launch:

```bash
python -m forza gui
```

## Scope rules

- SQL is the runtime source of truth.
- The GUI is the primary product surface.
- CLI changes should remain limited to operational workflows.
- Avoid adding parallel legacy/runtime sources such as JSON state files.
- Keep patches focused; do not mix packaging, documentation, and runtime behavior unless the change requires it.
- Do not commit local screenshots, databases, logs, generated PDFs, generated CSVs, or model-response artifacts.

## Pull requests

A useful PR includes:

- concise problem statement;
- summary of changed files;
- validation commands and results;
- screenshots or notes for visible GUI changes;
- migration/reset notes for database changes.

## Packaging changes

Beta packaging must use explicit allow-lists. Developer-only directories such as `tools/`, `scripts/`, `tests/`, `.git/`, and `.github/` should not be included in distributed application bundles.
