# Configuration

Status: current
Audience: developer, maintainer, LLM
Scope: `forza-config` + settings UI + CLI validation.

## File (`forza_config.ini`)

Parsed by `forza-config::load_config(path, strict)`; sections `paths`,
`user`, `llm`, `lmstudio`, `image`, `validation`, `pdf`, `prompt`, `ui`.
A missing file yields defaults **with a warning** (never silent). Unknown
`[section] key` entries warn (typo guard). Lenient mode falls back per value;
strict aborts on the first invalid one. Loader/writer agree on edge values
(`""`/`0` unset for optional ints, `y/n` bools, trimmed lowercase
`reasoning_mode`).

## Validation (`validate_config`)

Enforces non-empty endpoint/model/gamertag/paths, finite numbers, and the
ranges the settings UI advertises (tokens, temperature 0–2, retries 0–10,
timeouts, batch sizes, tps/elapsed windows, image/validation/UI bounds).
`forza.exe config-check` fails on warnings **or** errors (no false OK);
`run`/`rebuild`/`export` refuse to start on invalid config. `--strict` is a
global CLI flag; `--debug` is display-only and never changes parsing.

## Settings UI & save

`forza-app/src/services/settings.rs` builds snapshot rows (groups, editors,
min/max/step, pending/invalid badges) over the live config. Edits validate
via un-coalesced previews (monotonic `seq`, stale drops) and save through
`save_changes`: unrelated-field failures never block a valid edit, writes are
atomic (tmp + rename) with timestamped backups, and a changed gamertag
recomputes the frontier. `PENDING_SETTINGS` clears on save/discard.
