# Versioning Contract

Implementation: Rust (forza-rust/) — current. Legacy Python (forza/) frozen at 0.21.0-beta.1.
Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: application version, changelog, release labeling, and validation
Last verified: 2026-09-05
Supersedes: versioning rules implied by changelog entries
Related tests: unit tests in `forza-rust/crates/forza-cli` and `forza-app`

The project version is an operator-facing contract. It must identify the code
being run in the GUI, CLI help, packages, release notes, and release tags.

## Source Of Truth

- The workspace `Cargo.toml` `[workspace.package].version` (`0.1.0`) is the
  source of truth.
- `forza-app::APP_VERSION` is the build identity: package version plus git
  hash plus build time (`<version>+g<hash> built <time>`). The CLI
  (`forza.exe --version`, via `forza-cli`), the GUI title and About dialog,
  and every extraction-run row carry this identity so a database always
  reveals which binary produced it.
- `pyproject.toml` `[project].version` and `forza.version` are legacy Python
  surfaces. They must not be treated as the current version.
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
2. Update the workspace `Cargo.toml` version to the exact release version.
3. Confirm `forza-app::APP_VERSION` (and therefore `forza.exe --version`)
   reports the release version.
4. Run `forza.exe --help` and confirm the displayed workflow commands are
   current.
5. Smoke-test GUI startup and confirm the displayed version is current.
6. Run the validation gates in `docs/project_status.md`.
7. Tag using the same version as the workspace `Cargo.toml`.

## Known Issues

No known versioning issues are currently approved.
