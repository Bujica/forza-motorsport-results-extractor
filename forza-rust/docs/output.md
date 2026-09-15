# Output (CSV / PDF)

Status: current
Audience: developer, maintainer, LLM
Scope: `forza-output` — plans, rendering, export flows.

## CSV (`csv.rs`)

Columns (BOM + CRLF, minimal quoting, `dirty` as True/False, `None` → ""):
track, race_class, weather, temp, driver, car, best_lap, best_lap_ms, dirty,
source_file, race_date, image_format, dimensions. Empty exports write header
only; callers guard the empty case before announcing success.

## PDF (`pdf.rs`, dependency-free writer)

Cover (stats + external legend) → indexed TOC → per-track/class tables →
footer (`Page N` + TOC hotspot). TOC rows link to section destinations
(`sec-{i}`); the footer TOC rect covers the label glyphs; section page
numbers account for multi-page TOCs. Rows: player highlight, external tint,
alternation, red dirty-lap marker (gated by config), WinAnsi-encoded text
(€/™/smart punctuation mapped, `?` fallback otherwise), greedy wrap with
hard-split for spaceless tokens. `render_pdf` returns contributing source
files and archives any previous report with a collision-proof name (never
overwrites).

## Plans & flows

`build_pdf_plan_ext(rows, gamertag, external, …)` groups (trimmed track/class
keys), orders fastest-first with player tie-break, and computes stats.
Sources: `list_clean_flat` (best laps) + active external snapshot.
Entry points: Best Laps export buttons (CSV/PDF), CLI `export [--out PATH]
[--pdf]`. Empty plans write nothing.
