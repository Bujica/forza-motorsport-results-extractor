
# Quick Guide

Forza Motorsport Results Extractor extracts lap-time data from Forza Motorsport, 2023 release, post-race Results screen screenshots.

## Source checkout quick start

```cmd
cd forza-rust
cargo build -p forza-cli -p forza-gui
.\target\debug\forza.exe maintenance db-upgrade
.\target\debug\forza.exe maintenance db-doctor
.\target\debug\forza-gui.exe
```

## Beta bundle quick start

From the unpacked bundle folder:

```cmd
copy forza_config.ini.example forza_config.ini
forza.exe maintenance db-upgrade
forza.exe maintenance db-doctor
forza-gui.exe
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

## Common checks

```cmd
.\target\debug\forza.exe --version
.\target\debug\forza.exe config-check
.\target\debug\forza.exe maintenance db-doctor
```

For the beta bundle, run `forza.exe` from the bundle folder instead.
