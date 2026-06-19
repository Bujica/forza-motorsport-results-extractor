# Contracts Index

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: index of normative project behavior contracts
Last verified: 2026-06-16
Supersedes: contract sections scattered across `docs/DEVELOPER_GUIDE.md`
Related tests: see each contract

Contracts define how the project must behave. They are more authoritative than
guides, plans, and historical records.

| Contract | Scope |
| --- | --- |
| `database.md` | SQLite source of truth, evidence, schema, and integrity rules. |
| `review.md` | Review-case creation, correction, model-error evidence, and GUI expectations. |
| `best_laps.md` | Persisted frontier, best-lap status, and rebuild/recompute behavior. |
| `images_and_files.md` | Image file identity, rename/export/delete behavior, and file metadata. |
| `gui.md` | GUI architecture, threading, navigation, and usability rules. |
| `gui_signal_payloads.md` | PySide signal payload shape for object-typed GUI boundaries. |
| `rebuild.md` | Rebuild source of truth, derived-state regeneration, and idempotency. |
| `raw_artifacts.md` | Raw response and debug artifact integrity. |
| `configuration.md` | Runtime configuration ownership and propagation. |
| `versioning.md` | Application version, changelog, release labeling, and validation. |

When a change alters behavior in one of these areas, update the relevant
contract in the same commit.
