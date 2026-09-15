# Forza Motorsport Results Extractor — Rust Beta Manual

For testers using the Windows Rust beta bundle
(`ForzaMotorsportResultsExtractor-rust-*-windows-x64.zip`, Rust line `0.1.0`).

Target game: Forza Motorsport, 2023 release.
Target screenshot type: post-race Results screen.
Model runtime: your own local LM Studio endpoint (no model ships in this bundle).

## What is in the folder

| File | What it is |
| --- | --- |
| `forza-gui.exe` | The desktop app (primary surface — start here). |
| `forza.exe` | Command line: maintenance, controlled runs, exports. |
| `forza_config.ini.example` | Starter configuration template. |
| `RUST_BETA.md` | This manual. |
| `cars.txt`, `tracks.txt`, `data/external/track_aliases.json` | Reference data (read-only). |
| `data/input/` | Put your results screenshots here. |
| `data/forza.sqlite3` | The database (created automatically, see below). |
| `output/reports/`, `output/logs/`, `output/exports/` | Reports, logs, CSV exports. |
| `build_info.json` | Exact version + commit this bundle was built from. |

There are no `.bat` helpers: everything below happens inside the app.

## First run (3 steps)

1. **Open `forza-gui.exe`.** Missing pieces create themselves: the
   configuration file (from the example), the database, and any missing
   folders. No setup command needed.
2. **Point it at LM Studio.** In Settings, set the endpoint URL (default
   `http://127.0.0.1:1234/api/v1/chat`), the model name, and your
   `user.gamertag` (used to mark your own laps).
3. **Drop screenshots into `data/input/`** and press Run.

## Which database am I using?

Exactly one: the file shown in **Settings → Paths → `database_file`**
(absolute path), also visible in the footer bar and in About. The app never
searches for another database — if the configured file is missing it is
created empty; if its schema is too old or too new you get a recovery
dialog (migrate in place, back up and recreate, or quit untouched).

## Command line (optional)

All commands resolve paths against the folder of the given `--config`
(default `forza_config.ini` in the current folder):

```cmd
forza.exe maintenance db-upgrade
forza.exe maintenance db-doctor --json
forza.exe config-check
forza.exe run --limit 5
forza.exe --help
```

## Troubleshooting

- **Settings shows a path as `missing`**: the folder was deleted after
  startup. Recreate it (or restart the app, which recreates input/output
  folders) — or point the setting somewhere else and save.
- **Empty run, 0 images planned**: `data/input/` has no supported
  screenshots (png/jpg/webp of post-race Results screens).
- **LM Studio errors**: start LM Studio with the server on, load a vision
  model, and match the model name in Settings. `db-doctor --json` reports
  database-side issues, never model issues.
- **Starting over**: close the app and delete `data/forza.sqlite3`
  (plus `-shm`/`-wal` sidecars if present); the next launch recreates it.
