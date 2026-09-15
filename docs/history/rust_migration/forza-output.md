Status: historical
Audience: developer, maintainer, LLM
Lifecycle: temporary (superseded by `migration_report.md` in this directory)
Scope: detailed porting analysis of `forza-rust/crates/forza-output` crate
Last verified: 2026-08-27
Supersedes: none

# Detailed porting analysis — forza-output

## Overview

CSV export + PDF content planning and lightweight rendering. Ported from Python's `forza/output/csv.py` + `forza/output/pdf.py`. CSV is a complete, byte-compatible port; PDF content planning (`build_pdf_plan`) is fully ported but full ReportLab-style rendering remains unported (placeholder `render_pdf`).

| File | Lines | Python Source | Porting Status | Key Exports |
|------|-------|---------------|----------------|-------------|
| `src/lib.rs` | 9 | `forza/output/__init__.py` | Fully ported (structural) | Re-exports all public types/functions |
| `src/csv.rs` | 145 | `forza/output/csv.py` | **Fully ported** | `ExportRow`, `export_csv()`, `ExportError` |
| `src/pdf.rs` | 310 | `forza/output/pdf.py` | **Partially ported** (planning complete, rendering is lightweight placeholder) | `PdfDocumentPlan`, `build_pdf_plan()`, `render_pdf()` (text-based), `PdfRow`, `PdfTable`, `PdfSection` |
| `tests/output_golden.rs` | 151 | `tools/export_output_golden.py` + golden fixture | Fully ported (test harness) | 2 tests: CSV byte identity, PDF plan structural match |

## src/lib.rs — Crate aggregate + public API surface

Python functionality ported: None directly — this is a Rust module declaration and re-export layer. It mirrors the Python package structure (`forza/output/__init__.py`) which exports `export_csv` from `.csv` and `generate_pdf` from `.pdf`.

Status: **Fully ported (structural)**. Declares the two submodules and re-exports all public types/functions, matching the Python `__all__ = ["export_csv", "generate_pdf"]` contract.

Key functions/types exported:
- `ExportError`, `export_csv` (from `csv`)
- `PdfDocumentPlan`, `PdfRenderError`, `PdfRow`, `PdfSection`, `PdfTable`, `build_pdf_plan`, `render_pdf` (from `pdf`)

## src/csv.rs — Byte-compatible CSV writer

Python functionality ported from: `forza/output/csv.py`
- `_CSV_FIELDS` list (line 30-46 in Python)
- `export_csv(results, out_path)` function (line 49-96 in Python)
- The row flattening logic that maps `ExportLap` fields to dict keys

Status: **Fully ported**. Every field mapping is present and byte-compatible:
- UTF-8 BOM (`0xEF, 0xBB, 0xBF`) matches Python's `encoding="utf-8-sig"`
- CRLF line endings match Python's `newline=""` + `csv.DictWriter` behavior on Windows
- Boolean formatting uses `"True"/"False"` (matching Python's `str(bool)`)
- Float formatting (`fmt_float`) replicates Python's `str(float)` behavior: 80.0 stays "80.0", not "80"
- QUOTE_MINIMAL logic mirrors Python's csv module quoting rules
- None values become empty strings (matching Python's `{r.temp_f if r.temp_f is not None else ""}` pattern)

Key functions/types exported:
- `ExportError` — I/O error enum (`#[error("I/O error: {0}")]`)
- `ExportRow` — flat export row struct mirroring Python's `ExportLap` read model (15 fields, all present)
- `export_csv(rows: &[ExportRow], out_path: &Path) -> Result<usize, ExportError>` — main entry point; returns row count

**Notable differences from Python:**
- Rust builds the CSV into a `Vec<u8>` in-memory before writing (Python streams directly to file). This is an implementation detail but produces byte-identical output.
- No logging layer (Python uses `logging.getLogger("forza")` for warnings/info)

## src/pdf.rs — PDF content plan builder + lightweight renderer

Python functionality ported from: `forza/output/pdf.py`
- `_build_data_map()` function (line 307-374 in Python) — nested `{track → {class → [row]}}` structure
- Canonical track ordering via `track_order_key`, `track_order_map`
- Class ordering via `class_order_key`
- Per-bucket time sort with player-first tie-break: `(time_sec, not mine)` key
- CLASS_COLORS mapping (line 19 in Python imports from config)

Status: **Partially ported**. The content planning layer (`build_pdf_plan`) is fully ported and structurally identical to the Python `_build_data_map`. However, the full PDF rendering is a lightweight placeholder:

| Feature | Status |
|---------|--------|
| `build_pdf_plan` (data map + ordering) | **Fully ported** — deterministic plan matches Python's `_build_data_map` exactly |
| Class colors mapping | **Fully ported** — same hex values for E, D, C, B, A, TCR, S, R, P, X, Mixed |
| Track ordering (canonical `tracks.txt`) | **Fully ported** — uses `forza_domain::ordering` module |
| Player-first tie-break sort | **Fully ported** — same `(time_ms, !mine)` logic |
| External record handling | **Partially ported** — external flag is set but no external records are injected in the current API (Python's `_build_data_map` accepts `external_records`) |
| Lightweight text PDF (`render_pdf`) | **Ported as placeholder** — produces a valid `.pdf-1.4` file with Helvetica text, page breaks at 42 lines, TOC index. Intentionally kept below the planning layer per doc comment (line 165-169). |
| Full ReportLab layout rendering | **NOT ported** — Python uses `SimpleDocTemplate`, `Table`, `TableStyle`, `Paragraph`, `HRFlowable`, `KeepTogether`, `PageBreak`, `TableOfContents` with styled headers, colored backgrounds (ROW_PLAYER/ROW_EXTERNAL/ROW_ALT), dirty-lap red highlighting, Portuguese month names, footer with page numbers and TOC back-link |
| PDF archiving (`_archive_pdf`) | **NOT ported** — Python moves existing PDF to `archive/` subfolder with timestamp |
| Config integration (dirty_lap_symbol, show_dirty_lap_symbol) | **NOT ported** — Rust version has no config parameter for dirty lap symbol display |

Key functions/types exported:
- `PdfRow` — rendered row struct (driver, car, time_str, dirty, mine, time_ms, temp_c, external)
- `PdfTable` — class table struct (class, color_hex, rows)
- `PdfSection` — track section struct (track, tables)
- `PdfDocumentPlan` — full document plan (gamertag, stats, sections)
- `PdfStats` — summary stats (tracks, classes, laps)
- `PdfRenderError` — I/O error enum
- `build_pdf_plan(rows: &[ExportRow], gamertag: &str, track_order: &[String]) -> PdfDocumentPlan` — main content planner
- `render_pdf(plan: &PdfDocumentPlan, path: &Path) -> Result<(), PdfRenderError>` — lightweight PDF writer

## tests/output_golden.rs — Golden-file test harness

Python functionality referenced from:
- `tools/export_output_golden.py` — generates the golden fixture by running both Python CSV export and `_build_data_map` on synthetic rows
- `forza/output/csv.py::export_csv` — produces the `csv_b64` golden bytes
- `forza/output/pdf.py::_build_data_map` — produces the `pdf_plan` golden JSON

Status: **Fully ported (test harness)**. The test validates:
1. `csv_bytes_are_identical_to_python_writer()` — asserts byte-identical CSV output against base64-encoded Python writer output
2. `pdf_plan_matches_python_data_map_and_ordering()` — asserts structural equality of the PDF plan (gamertag, stats, sections order, tables, rows with all fields)

Key test data:
- 3 synthetic `ExportRow` instances: Fuji Speedway A-class (2 rows), Le Mans Full Circuit TCR-class (1 row)
- Canonical track order loaded from `assets/tracks.txt`
- Golden fixture at `forza-rust/fixtures/expected/output_golden.json`

Test assertions cover:
- CSV byte identity (BOM, CRLF, quoting, field ordering)
- PDF plan gamertag match
- PDF plan stats (tracks=2, classes=2, laps=3)
- Section order (Fuji before Le Mans per canonical track list)
- Table class and color_hex values
- Row fields: driver, car, time_str, time_ms, dirty, mine, temp_c

## Overall assessment

The CSV export is a complete, byte-compatible port. The PDF content planning (`build_pdf_plan`) is also fully ported and tested against the Python `_build_data_map`. However, the full ReportLab-style PDF rendering with styled tables, colored backgrounds, dirty-lap symbols, Portuguese month names, TOC bookmarks, and footer pages remains unported — `render_pdf` produces a valid but minimal text-based PDF as an interim placeholder.
