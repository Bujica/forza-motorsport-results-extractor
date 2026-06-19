# Tools

Status: public beta
Audience: maintainers and release builders

This directory intentionally contains only public build tooling.

## Supported

- `build_windows_beta.py` - builds the Windows beta distribution using the
  PyInstaller spec under `packaging/`, writes `build_info.json`, stages the
  portable application folder, and creates the release ZIP.

Internal audit, diagnosis, maintainer workflow, and local triage scripts are
not part of the public beta baseline. They remain in the private development
repository when needed.
