
# Quick Guide

Forza Motorsport Results Extractor extracts lap-time data from Forza Motorsport, 2023 release, post-race Results screen screenshots.

## Source checkout quick start (current: Rust)

```cmd
cd forza-rust
cargo build -p forza-cli -p forza-gui
.\target\debug\forza.exe maintenance db-upgrade
.\target\debug\forza.exe maintenance db-doctor
.\target\debug\forza-gui.exe
```

## Source checkout quick start (legacy Python reference)

```cmd
pip install -e ".[dev,gui]"
python -m forza maintenance db-upgrade
python -m forza maintenance db-doctor --json
python -m forza gui
```

## Beta bundle quick start

The shipped beta bundle below is built from the legacy Python line
(PyInstaller — see `docs/release/beta_packaging.md`). A Rust-built bundle
(`forza.exe` + `forza-gui.exe` via `cargo build --release`) is not packaged
yet; from source, run the binaries from `forza-rust/target/debug/` (or
`release/`) as shown above.

From the unpacked bundle folder:

```cmd
copy forza_config.ini.example forza_config.ini
fmre-cli.exe maintenance db-upgrade
fmre-cli.exe maintenance db-doctor --json
"Forza Motorsport Results Extractor.exe"
```

Put supported screenshots here when using the beta bundle:

```text
data\input
```

Use **Images -> Scan input folder** in the GUI after copying screenshots.

## Supported screenshots

Supported:

- Forza Motorsport, 2023 release.
- Post-race Results screen.
- Screenshots clear enough for a local vision model to read driver, car, class, track, and lap-time data.

Not supported as a beta target:

- Forza Horizon.
- Older Forza Motorsport layouts.
- Leaderboard-only screens.
- Telemetry overlays.
- Arbitrary racing-game screenshots.

## Common checks (current: Rust)

```cmd
.\target\debug\forza.exe --version
.\target\debug\forza.exe config-check
```

## Common checks (legacy Python reference)

```cmd
python -m forza --version
python -m forza config-check
python -m forza maintenance db-doctor --json
```

For the beta bundle, replace `python -m forza` with `fmre-cli.exe`.
