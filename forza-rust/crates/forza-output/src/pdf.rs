//! Best-laps PDF renderer, ported from `forza/output/pdf.py`.
//!
//! The deterministic content plan (`build_pdf_plan*`) mirrors the Python
//! `_build_data_map` + ordering layer; `render_pdf` draws it with a
//! dependency-free PDF writer: cover page, track-index TOC with clickable
//! links, styled class tables (row colours, red dirty-lap highlighting),
//! page-number footer, and timestamped archiving of previous reports.

use std::collections::HashSet;
use std::path::Path;

use chrono::Datelike;

use forza_domain::lap::strip_dirty_symbol;
use forza_domain::ordering::{class_order_key, track_order_key, track_order_map};

use crate::csv::ExportRow;

/// One rendered row inside a class table.
#[derive(Debug, Clone, PartialEq)]
pub struct PdfRow {
    pub driver: String,
    pub car: String,
    pub time_str: String,
    pub dirty: bool,
    pub mine: bool,
    /// Integer milliseconds — the domain ordering contract.
    pub time_ms: i64,
    pub temp_c: Option<f64>,
    pub weather: String,
    /// External/community records have no source file.
    pub external: bool,
    pub source_file: Option<String>,
}

/// One external/community best-lap record merged into the tables.
#[derive(Debug, Clone, PartialEq)]
pub struct PdfExternalRecord {
    pub track: String,
    pub race_class: String,
    pub driver: String,
    pub car: String,
    pub best_lap: String,
    pub best_lap_ms: i64,
}

/// Config-driven render flags (mirrors `cfg.pdf` usage in `pdf.py`).
#[derive(Debug, Clone, PartialEq)]
pub struct PdfRenderOptions {
    pub show_dirty_symbol: bool,
    pub dirty_symbol: String,
}

impl Default for PdfRenderOptions {
    fn default() -> Self {
        PdfRenderOptions {
            show_dirty_symbol: true,
            dirty_symbol: "\u{2020}".to_string(),
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct PdfTable {
    pub class: String,
    pub color_hex: String,
    pub rows: Vec<PdfRow>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PdfSection {
    pub track: String,
    pub tables: Vec<PdfTable>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PdfDocumentPlan {
    pub gamertag: String,
    pub stats: PdfStats,
    pub sections: Vec<PdfSection>,
    pub external_count: usize,
    pub options: PdfRenderOptions,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PdfStats {
    pub tracks: usize,
    pub classes: usize,
    pub laps: usize,
}

#[derive(Debug, thiserror::Error)]
pub enum PdfRenderError {
    #[error("I/O error: {0}")]
    Io(String),
}

fn class_colors(class: &str) -> &'static str {
    match class {
        "E" => "#C7368E",
        "D" => "#127F85",
        "C" => "#BB7A00",
        "B" => "#C54E00",
        "A" => "#992800",
        "TCR" => "#1E90FF",
        "S" => "#613BBF",
        "R" => "#105DAB",
        "P" => "#0C8540",
        "X" => "#006000",
        "Mixed" => "#555555",
        _ => "#000000",
    }
}

/// Build the deterministic document plan (the report's list content).
///
/// `track_order` is the canonical track list defining section order.
/// External/community records are merged into the same buckets, marked
/// external, and never contribute source files.
pub fn build_pdf_plan(
    rows: &[ExportRow],
    gamertag: &str,
    track_order: &[String],
) -> PdfDocumentPlan {
    build_pdf_plan_ext(
        rows,
        gamertag,
        track_order,
        &[],
        PdfRenderOptions::default(),
    )
}

/// Extended plan builder: external records plus config-driven dirty-symbol
/// rendering, matching `generate_pdf(results, ..., external_records=...)`.
pub fn build_pdf_plan_ext(
    rows: &[ExportRow],
    gamertag: &str,
    track_order: &[String],
    external_records: &[PdfExternalRecord],
    options: PdfRenderOptions,
) -> PdfDocumentPlan {
    let gamertag_lower = gamertag.to_lowercase();

    // track → class → rows
    let mut data_map: std::collections::BTreeMap<
        String,
        std::collections::BTreeMap<String, Vec<PdfRow>>,
    > = Default::default();

    for row in rows {
        // Trim like the external pass below: "Fuji " vs "Fuji" must not
        // become separate sections/TOC entries and split leaderboards.
        let track = {
            let t = row.track.trim();
            if t.is_empty() {
                "Unknown".to_string()
            } else {
                t.to_string()
            }
        };
        let cls = row.race_class.trim().to_string();
        data_map
            .entry(track)
            .or_default()
            .entry(cls)
            .or_default()
            .push(PdfRow {
                driver: row.driver.clone(),
                car: row.car.clone(),
                time_str: row.best_lap.clone().unwrap_or_default(),
                dirty: row.dirty,
                mine: row.driver.trim().to_lowercase() == gamertag_lower,
                time_ms: row.best_lap_ms.unwrap_or(i64::MAX),
                temp_c: row.temp_c,
                weather: row.weather.clone().unwrap_or_default(),
                external: false,
                source_file: row.source_file.clone(),
            });
    }

    // Pass 2: external records (no temp, dry weather, never "mine").
    for rec in external_records {
        let track = rec.track.trim().to_string();
        let cls = rec.race_class.trim().to_string();
        if track.is_empty() || cls.is_empty() {
            continue;
        }
        data_map
            .entry(track)
            .or_default()
            .entry(cls)
            .or_default()
            .push(PdfRow {
                driver: rec.driver.trim().to_string(),
                car: rec.car.trim().to_string(),
                time_str: rec.best_lap.trim().to_string(),
                dirty: false,
                mine: false,
                time_ms: rec.best_lap_ms,
                temp_c: None,
                weather: "dry".to_string(),
                external: true,
                source_file: None,
            });
    }

    // Sort every bucket: fastest first, player before others on tie
    // (Python key: (time_sec, not mine)).
    for classes in data_map.values_mut() {
        for bucket in classes.values_mut() {
            bucket.sort_by(|a, b| a.time_ms.cmp(&b.time_ms).then_with(|| b.mine.cmp(&a.mine)));
        }
    }

    let order_index = track_order_map(track_order);
    let mut sorted_tracks: Vec<&String> = data_map.keys().collect();
    sorted_tracks.sort_by_key(|t| track_order_key(t, &order_index));

    let mut sections = Vec::new();
    for track in sorted_tracks {
        let classes = &data_map[track];
        let mut sorted_classes: Vec<&String> = classes.keys().collect();
        sorted_classes.sort_by_key(|c| class_order_key(c));
        let mut tables = Vec::new();
        for cls in sorted_classes {
            let rows = &classes[cls];
            tables.push(PdfTable {
                class: cls.clone(),
                color_hex: class_colors(cls).to_string(),
                rows: rows.clone(),
            });
        }
        sections.push(PdfSection {
            track: track.clone(),
            tables,
        });
    }

    let stats = PdfStats {
        tracks: sections.len(),
        classes: sections.iter().map(|s| s.tables.len()).sum(),
        laps: sections
            .iter()
            .flat_map(|s| s.tables.iter())
            .map(|t| t.rows.len())
            .sum(),
    };

    PdfDocumentPlan {
        gamertag: gamertag.to_string(),
        stats,
        sections,
        external_count: external_records.len(),
        options,
    }
}

// ── Archiving ────────────────────────────────────────────────────────────────

/// Move an existing report to `archive/` with a timestamp suffix, mirroring
/// `_archive_pdf` — the previous report stays comparable after a rebuild.
fn archive_pdf(pdf_path: &Path) -> Result<(), PdfRenderError> {
    if !pdf_path.exists() {
        return Ok(());
    }
    let parent = pdf_path.parent().unwrap_or_else(|| Path::new("."));
    let archive_dir = parent.join("archive");
    std::fs::create_dir_all(&archive_dir).map_err(|e| PdfRenderError::Io(e.to_string()))?;
    // Second-resolution stamps collide when two renders land in the same
    // second (double-click / script): never overwrite a previous archive.
    let ts = chrono::Local::now().format("%Y%m%d_%H%M%S");
    let stem = pdf_path
        .file_stem()
        .and_then(|n| n.to_str())
        .unwrap_or("report");
    let ext = pdf_path
        .extension()
        .map(|e| format!(".{}", e.to_string_lossy()))
        .unwrap_or_default();
    let mut dest = archive_dir.join(format!("{stem}_{ts}{ext}"));
    let mut counter = 2u32;
    while dest.exists() {
        dest = archive_dir.join(format!("{stem}_{ts}-{counter}{ext}"));
        counter += 1;
    }
    if std::fs::rename(pdf_path, &dest).is_err() {
        // Cross-device moves need copy + delete, like shutil.move.
        std::fs::copy(pdf_path, &dest).map_err(|e| PdfRenderError::Io(e.to_string()))?;
        std::fs::remove_file(pdf_path).map_err(|e| PdfRenderError::Io(e.to_string()))?;
    }
    Ok(())
}

// ── Colour constants ─────────────────────────────────────────────────────────

const ROW_PLAYER: Rgb = Rgb(1.0, 0.9725, 0.8627); // #FFF8DC warm yellow
const ROW_EXTERNAL: Rgb = Rgb(0.8392, 0.9176, 0.9725); // #D6EAF8 light blue
const ROW_ALT: Rgb = Rgb(0.9725, 0.9765, 0.9804); // #F8F9FA light grey
const DARK: Rgb = Rgb(0.1725, 0.2392, 0.3137); // #2C3E50
const GREY: Rgb = Rgb(0.4980, 0.5490, 0.5529); // #7F8C8D
const GREY_LIGHT: Rgb = Rgb(0.5843, 0.6471, 0.6510); // #95A5A6
const GRID: Rgb = Rgb(0.7412, 0.7647, 0.7804); // #BDC3C7
const TOC_ENTRY: Rgb = Rgb(0.2039, 0.2863, 0.3686); // #34495E
const RED: Rgb = Rgb(0.9059, 0.2980, 0.2353); // #E74C3C
const WHITE: Rgb = Rgb(1.0, 1.0, 1.0);
const BLACK: Rgb = Rgb(0.0, 0.0, 0.0);

#[derive(Clone, Copy)]
struct Rgb(f64, f64, f64);

fn hex_rgb(hex: &str) -> Rgb {
    let v = hex.trim_start_matches('#');
    let byte = |i: usize| u8::from_str_radix(&v[i..i + 2], 16).unwrap_or(0) as f64 / 255.0;
    Rgb(byte(0), byte(2), byte(4))
}

const MONTHS_PT: [&str; 12] = [
    "Janeiro",
    "Fevereiro",
    "Março",
    "Abril",
    "Maio",
    "Junho",
    "Julho",
    "Agosto",
    "Setembro",
    "Outubro",
    "Novembro",
    "Dezembro",
];

// ── Core font metrics (AFM widths, units of 1/1000 em) ───────────────────────

#[derive(Clone, Copy, PartialEq)]
enum Font {
    Regular,
    Bold,
}

impl Font {
    fn resource(self) -> &'static str {
        match self {
            Font::Regular => "F1",
            Font::Bold => "F2",
        }
    }
}

const HELVETICA_WIDTHS: [u16; 95] = [
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556,
    556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667,
    611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667,
    667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500,
    222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
];

const HELVETICA_BOLD_WIDTHS: [u16; 95] = [
    278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556,
    556, 556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667,
    611, 778, 722, 278, 556, 722, 611, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667,
    667, 611, 333, 278, 333, 584, 556, 333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556,
    278, 889, 611, 611, 611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584,
];

fn char_width(font: Font, ch: char) -> f64 {
    let table = match font {
        Font::Regular => &HELVETICA_WIDTHS,
        Font::Bold => &HELVETICA_BOLD_WIDTHS,
    };
    let idx = match ch {
        c if (' '..='~').contains(&c) => c as usize - ' ' as usize,
        '\u{2020}' | '\u{2013}' | '\u{2014}' => 40, // approximate via 'F'
        // WinAnsi extras from `winansi_bytes` measure approximately (exact
        // AFM entries vary by foundry); centering may be off by a point on
        // exotic glyphs, but the text itself now renders instead of '?'.
        _ => 12, // approximate via ','
    };
    table[idx] as f64
}

fn text_width(font: Font, size: f64, s: &str) -> f64 {
    s.chars().map(|c| char_width(font, c)).sum::<f64>() * size / 1000.0
}

/// Greedy word wrap to fit a cell (ReportLab wraps paragraphs the same way).
/// A single spaceless token wider than the cell is hard-split by characters —
/// otherwise a 25+ char gamertag/car overflows the column grid (ReportLab
/// breaks such words too; the old code drew past the border).
fn wrap_text(s: &str, font: Font, size: f64, max_width: f64) -> Vec<String> {
    fn split_token(token: &str, font: Font, size: f64, max_width: f64) -> Vec<String> {
        if text_width(font, size, token) <= max_width {
            return vec![token.to_string()];
        }
        let mut parts = Vec::new();
        let mut cur = String::new();
        for ch in token.chars() {
            let probe = format!("{cur}{ch}");
            if !cur.is_empty() && text_width(font, size, &probe) > max_width {
                parts.push(std::mem::take(&mut cur));
            }
            cur.push(ch);
        }
        if !cur.is_empty() {
            parts.push(cur);
        }
        if parts.is_empty() {
            parts.push(token.to_string());
        }
        parts
    }

    let mut lines = Vec::new();
    let mut current = String::new();
    for word in s.split_whitespace() {
        for piece in split_token(word, font, size, max_width) {
            let candidate = if current.is_empty() {
                piece.clone()
            } else {
                format!("{current} {piece}")
            };
            if !current.is_empty() && text_width(font, size, &candidate) > max_width {
                lines.push(std::mem::take(&mut current));
                current = piece;
            } else {
                current = candidate;
            }
        }
    }
    if !current.is_empty() || lines.is_empty() {
        lines.push(current);
    }
    lines
}

// ── WinAnsi text encoding ────────────────────────────────────────────────────

/// Encode to WinAnsiEncoding bytes (Portuguese accents live in Latin-1; the
/// typographic symbols the report uses map to their WinAnsi slots).
fn winansi_bytes(s: &str) -> Vec<u8> {
    s.chars()
        .map(|c| match c {
            '\u{2020}' => 0x86, // †
            '\u{2021}' => 0x87, // ‡
            '\u{2022}' => 0x95, // •
            '\u{2013}' => 0x96, // –
            '\u{2014}' => 0x97, // —
            '\u{2018}' => 0x91,
            '\u{2019}' => 0x92,
            '\u{201C}' => 0x93,
            '\u{201D}' => 0x94,
            '\u{2026}' => 0x85, // …
            // Remaining WinAnsi punctuation (previously fell through to '?',
            // corrupting gamertags/covers containing €, ™, smart quotes…).
            '\u{20AC}' => 0x80,                           // €
            '\u{201A}' => 0x82,                           // ‚
            '\u{0192}' => 0x83,                           // ƒ
            '\u{201E}' => 0x84,                           // „
            '\u{2030}' => 0x89,                           // ‰
            '\u{0160}' => 0x8A,                           // Š
            '\u{2039}' => 0x8B,                           // ‹
            '\u{0152}' => 0x8C,                           // Œ
            '\u{017D}' => 0x8E,                           // Ž
            '\u{2010}' | '\u{2011}' | '\u{2012}' => 0x96, // hyphen variants → –
            '\u{2122}' => 0x99,                           // ™
            '\u{0161}' => 0x9A,                           // š
            '\u{203A}' => 0x9B,                           // ›
            '\u{0153}' => 0x9C,                           // œ
            '\u{017E}' => 0x9E,                           // ž
            '\u{0178}' => 0x9F,                           // Ÿ
            c if (' '..='~').contains(&c) => c as u8,
            c if ('\u{A0}'..='\u{FF}').contains(&c) => c as u8,
            _ => b'?',
        })
        .collect()
}

fn pdf_escape(s: &str) -> Vec<u8> {
    let bytes = winansi_bytes(s);
    let mut out = Vec::with_capacity(bytes.len());
    for b in bytes {
        match b {
            b'\\' | b'(' | b')' => {
                out.push(b'\\');
                out.push(b);
            }
            _ => out.push(b),
        }
    }
    out
}

fn num(v: f64) -> String {
    let rounded = (v * 100.0).round() / 100.0;
    if (rounded - rounded.trunc()).abs() < f64::EPSILON {
        format!("{}", rounded as i64)
    } else {
        format!("{rounded}")
    }
}

// ── Page drawing primitives ──────────────────────────────────────────────────

/// Clickable rectangle jumping to a named destination (`/Dests` in the
/// catalog). Coordinates are PDF points with the origin at bottom-left.
struct PdfLink {
    x0: f64,
    y0: f64,
    x1: f64,
    y1: f64,
    dest: String,
}

#[derive(Default)]
struct Page {
    ops: String,
    links: Vec<PdfLink>,
}

impl Page {
    fn text(&mut self, font: Font, size: f64, color: Rgb, x: f64, y: f64, s: &str) {
        self.ops.push_str(&format!(
            "BT /{} {} Tf {} {} {} rg {} {} Td (",
            font.resource(),
            num(size),
            num(color.0),
            num(color.1),
            num(color.2),
            num(x),
            num(y)
        ));
        self.ops.extend(pdf_escape(s).iter().map(|&b| b as char));
        self.ops.push_str(") Tj ET\n");
    }

    fn rect_fill(&mut self, color: Rgb, x: f64, y: f64, w: f64, h: f64) {
        self.ops.push_str(&format!(
            "{} {} {} rg {} {} {} {} re f\n",
            num(color.0),
            num(color.1),
            num(color.2),
            num(x),
            num(y),
            num(w),
            num(h)
        ));
    }

    fn line(&mut self, color: Rgb, width: f64, x1: f64, y1: f64, x2: f64, y2: f64) {
        self.ops.push_str(&format!(
            "{} w {} {} {} RG {} {} m {} {} l S\n",
            num(width),
            num(color.0),
            num(color.1),
            num(color.2),
            num(x1),
            num(y1),
            num(x2),
            num(y2)
        ));
    }
}

// ── Geometry constants (A4 portrait, ReportLab margins) ──────────────────────

const PAGE_W: f64 = 595.0;
const PAGE_H: f64 = 842.0;
const MARGIN_SIDE: f64 = 30.0;
const MARGIN_TOP: f64 = 40.0;
const MARGIN_BOTTOM: f64 = 40.0;
const CONTENT_W: f64 = PAGE_W - 2.0 * MARGIN_SIDE; // 535
const CONTENT_TOP: f64 = PAGE_H - MARGIN_TOP; // 802
const TOC_ENTRIES_PER_PAGE: usize = 52;

const COL_WIDTHS: [f64; 6] = [35.0, 105.0, 195.0, 75.0, 55.0, 30.0];
const CELL_PAD_V: f64 = 4.0;
const CELL_PAD_H: f64 = 6.0;
const CELL_LEADING: f64 = 10.0;
const HEADER_LEADING: f64 = 11.0;

struct Renderer {
    pages: Vec<Page>,
    cursor: f64,
}

impl Renderer {
    fn new() -> Self {
        // No page is allocated until the first section calls `new_page`,
        // mirroring the PageBreak that ends the TOC in the Python layout.
        Renderer {
            pages: Vec::new(),
            cursor: CONTENT_TOP,
        }
    }

    fn current(&mut self) -> &mut Page {
        if self.pages.is_empty() {
            self.pages.push(Page::default());
        }
        self.pages
            .last_mut()
            .unwrap_or_else(|| unreachable!("page was just pushed"))
    }

    fn page_number(&self) -> usize {
        self.pages.len()
    }

    fn new_page(&mut self) {
        self.pages.push(Page::default());
        self.cursor = CONTENT_TOP;
    }

    fn ensure_space(&mut self, height: f64) {
        if self.cursor - height < MARGIN_BOTTOM {
            self.new_page();
        }
    }
}

/// Python `str.title()` for the weather column.
fn title_case(s: &str) -> String {
    s.split_whitespace()
        .map(|word| {
            let mut chars = word.chars();
            match chars.next() {
                Some(first) => {
                    first.to_uppercase().collect::<String>() + &chars.as_str().to_lowercase()
                }
                None => String::new(),
            }
        })
        .collect::<Vec<_>>()
        .join(" ")
}

/// Python str(float): 80.0 → "80.0", 26.7 → "26.7".
fn fmt_float(v: f64) -> String {
    if v == v.trunc() && v.abs() < 1e15 {
        format!("{v:.1}")
    } else {
        format!("{v}")
    }
}

// ── Main entry point ─────────────────────────────────────────────────────────

/// Render the best-laps PDF. Returns the set of source files that contributed
/// rows (mirrors `generate_pdf`'s `used_files` return value).
pub fn render_pdf(plan: &PdfDocumentPlan, path: &Path) -> Result<HashSet<String>, PdfRenderError> {
    let mut used_files: HashSet<String> = HashSet::new();
    if plan.stats.laps == 0 && plan.external_count == 0 {
        return Ok(used_files);
    }

    path.parent()
        .filter(|p| !p.as_os_str().is_empty())
        .map(std::fs::create_dir_all)
        .transpose()
        .map_err(|e| PdfRenderError::Io(e.to_string()))?;
    archive_pdf(path)?;

    // ── Section pages (their page numbers feed the TOC) ─────────────────────
    let mut renderer = Renderer::new();
    let mut heading_pages: Vec<usize> = Vec::with_capacity(plan.sections.len());
    for section in &plan.sections {
        renderer.new_page();
        heading_pages.push(renderer.page_number());
        draw_track_heading(&mut renderer, &section.track);

        for table in &section.tables {
            draw_table(&mut renderer, table, &plan.options);
            for row in &table.rows {
                if let Some(file) = row.source_file.as_deref().filter(|f| !f.is_empty()) {
                    used_files.insert(file.to_string());
                }
            }
            renderer.ensure_space(8.0 + HEADER_ROW_H);
            renderer.cursor -= 8.0;
        }
    }

    let mut pages = renderer.pages;
    // TOC page count is known before rendering sections: with >52 tracks the
    // index spans several pages and every section number shifts by that many
    // (the old hardcoded `+ 1` printed wrong page numbers on full reports).
    let toc_page_count = plan.sections.len().div_ceil(TOC_ENTRIES_PER_PAGE).max(1);
    let heading_page_numbers: Vec<usize> =
        heading_pages.iter().map(|p| p + toc_page_count).collect();

    // ── TOC pages (each row links to its section) ────────────────────────────
    let mut toc_pages: Vec<Page> = Vec::new();
    {
        let entries = plan.sections.len();
        for index in 0..toc_page_count {
            let mut page = Page::default();
            let cursor_top = CONTENT_TOP;
            let title_baseline = cursor_top - 16.0;
            page.text(
                Font::Bold,
                16.0,
                DARK,
                MARGIN_SIDE,
                title_baseline,
                "Track Index",
            );
            let chunk_start = index * TOC_ENTRIES_PER_PAGE;
            let chunk_end = ((index + 1) * TOC_ENTRIES_PER_PAGE).min(entries);
            let mut y = title_baseline - 12.0 - 10.0;
            for (entry_idx, section) in plan.sections[chunk_start..chunk_end].iter().enumerate() {
                let global_idx = chunk_start + entry_idx;
                let page_no = heading_page_numbers[global_idx];
                page.text(
                    Font::Regular,
                    10.0,
                    TOC_ENTRY,
                    MARGIN_SIDE + 10.0,
                    y,
                    &section.track,
                );
                let number = page_no.to_string();
                let width = text_width(Font::Regular, 10.0, &number);
                page.text(
                    Font::Regular,
                    10.0,
                    TOC_ENTRY,
                    PAGE_W - MARGIN_SIDE - width,
                    y,
                    &number,
                );
                // The whole row is clickable (baseline y is 10pt text: glyphs
                // span roughly y-2..y+8; pad generously for touch/mouse).
                page.links.push(PdfLink {
                    x0: MARGIN_SIDE,
                    y0: y - 4.0,
                    x1: PAGE_W - MARGIN_SIDE,
                    y1: y + 12.0,
                    dest: format!("sec-{global_idx}"),
                });
                y -= 14.0;
            }
            toc_pages.push(page);
        }
    }

    // ── Cover page ───────────────────────────────────────────────────────────
    let cover = build_cover_page(plan);
    let mut ordered = vec![cover];
    ordered.extend(toc_pages);
    ordered.append(&mut pages);
    // Named destinations: the TOC itself plus one per section heading.
    // Ordered-page index of section i = cover + TOC pages + renderer-local.
    let mut dests: Vec<(String, usize)> = vec![("toc".to_string(), 1)];
    for (i, &renderer_page) in heading_pages.iter().enumerate() {
        dests.push((format!("sec-{i}"), 1 + toc_page_count + (renderer_page - 1)));
    }

    // ── Footer on every page ─────────────────────────────────────────────────
    for (idx, page) in ordered.iter_mut().enumerate() {
        let label = format!(
            "Forza Motorsport \u{2014} Best Laps \u{2014} Page {}",
            idx + 1
        );
        let width = text_width(Font::Regular, 7.0, &label);
        page.text(
            Font::Regular,
            7.0,
            GREY_LIGHT,
            (PAGE_W - width) / 2.0,
            15.0,
            &label,
        );
        page.text(Font::Regular, 7.0, GREY, PAGE_W - MARGIN_SIDE, 15.0, "TOC");
    }

    write_pdf_file(&ordered, path, &dests)?;
    Ok(used_files)
}

const HEADER_ROW_H: f64 = HEADER_LEADING + 2.0 * CELL_PAD_V;

fn draw_track_heading(renderer: &mut Renderer, track: &str) {
    let height = 16.0 + 2.0 * 6.0; // leading + border padding
    let top = renderer.cursor;
    let baseline = top - 6.0 - 13.0 * 0.78;
    let page = renderer.current();
    page.rect_fill(DARK, MARGIN_SIDE, top - height, CONTENT_W, height);
    page.text(Font::Bold, 13.0, WHITE, MARGIN_SIDE + 10.0, baseline, track);
    renderer.cursor = top - height - 8.0;
}

fn draw_table(renderer: &mut Renderer, table: &PdfTable, options: &PdfRenderOptions) {
    let color = hex_rgb(&table.color_hex);
    let header_labels: [&str; 6] = [
        &table.class,
        "Driver",
        "Car",
        "Best Lap",
        "Weather",
        "\u{B0}C",
    ];

    // Pre-wrap every data row into cell lines to compute heights. The dirty
    // symbol is appended only when enabled; red highlighting follows the same
    // condition.
    let mut dirty_highlight: Vec<bool> = Vec::with_capacity(table.rows.len());
    let wrapped: Vec<[Vec<String>; 6]> = table
        .rows
        .iter()
        .map(|row| {
            let time_clean = strip_dirty_symbol(&row.time_str);
            let highlight = options.show_dirty_symbol && row.dirty;
            dirty_highlight.push(highlight);
            let time_text = if highlight {
                format!("{} {}", time_clean, options.dirty_symbol)
            } else {
                time_clean
            };
            [
                vec![String::new()],
                wrap_text(
                    &row.driver,
                    Font::Regular,
                    8.0,
                    COL_WIDTHS[1] - 2.0 * CELL_PAD_H,
                ),
                wrap_text(
                    &row.car,
                    Font::Regular,
                    8.0,
                    COL_WIDTHS[2] - 2.0 * CELL_PAD_H,
                ),
                wrap_text(
                    &time_text,
                    Font::Regular,
                    8.0,
                    COL_WIDTHS[3] - 2.0 * CELL_PAD_H,
                ),
                wrap_text(
                    &title_case(&row.weather),
                    Font::Regular,
                    8.0,
                    COL_WIDTHS[4] - 2.0 * CELL_PAD_H,
                ),
                vec![match row.temp_c {
                    Some(v) => fmt_float(v),
                    None => "-".to_string(),
                }],
            ]
        })
        .collect();

    let row_heights: Vec<f64> = wrapped
        .iter()
        .map(|cells| {
            cells.iter().map(|lines| lines.len()).max().unwrap_or(1) as f64 * CELL_LEADING
                + 2.0 * CELL_PAD_V
        })
        .collect();
    let total: f64 = HEADER_ROW_H + row_heights.iter().sum::<f64>();

    if total <= CONTENT_TOP - MARGIN_BOTTOM {
        // KeepTogether: the whole table moves to a fresh page when needed.
        if renderer.cursor - total < MARGIN_BOTTOM {
            renderer.new_page();
        }
        draw_table_block(
            renderer,
            table,
            color,
            &header_labels,
            &wrapped,
            &dirty_highlight,
            0,
            table.rows.len(),
        );
        return;
    }

    // Taller than a full page: split, repeating the header per page.
    let mut first = 0usize;
    loop {
        if renderer.cursor - HEADER_ROW_H - row_heights[first] < MARGIN_BOTTOM {
            renderer.new_page();
        }
        let mut end = first;
        let mut used = HEADER_ROW_H;
        while end < table.rows.len() && used + row_heights[end] <= renderer.cursor - MARGIN_BOTTOM {
            used += row_heights[end];
            end += 1;
        }
        if end == first {
            end = first + 1;
        }
        draw_table_block(
            renderer,
            table,
            color,
            &header_labels,
            &wrapped,
            &dirty_highlight,
            first,
            end,
        );
        first = end;
        if first < table.rows.len() {
            renderer.new_page();
        } else {
            break;
        }
    }
}

/// Draw one contiguous block of rows; the header repeats on every block.
#[allow(clippy::too_many_arguments)]
fn draw_table_block(
    renderer: &mut Renderer,
    table: &PdfTable,
    color: Rgb,
    header_labels: &[&str; 6],
    wrapped: &[[Vec<String>; 6]],
    dirty_highlight: &[bool],
    first_row: usize,
    end_row: usize,
) {
    let block_heights: Vec<f64> = (first_row..end_row)
        .map(|i| {
            wrapped[i]
                .iter()
                .map(|lines| lines.len())
                .max()
                .unwrap_or(1) as f64
                * CELL_LEADING
                + 2.0 * CELL_PAD_V
        })
        .collect();
    let block_total = HEADER_ROW_H + block_heights.iter().sum::<f64>();

    let top = renderer.cursor;
    let page = renderer.current();
    let table_bottom = top - block_total;
    let right = MARGIN_SIDE + COL_WIDTHS.iter().sum::<f64>();

    // Header background + labels.
    page.rect_fill(
        color,
        MARGIN_SIDE,
        top - HEADER_ROW_H,
        right - MARGIN_SIDE,
        HEADER_ROW_H,
    );
    for (col, label) in header_labels.iter().enumerate() {
        if label.is_empty() {
            continue;
        }
        let width = text_width(Font::Bold, 9.0, label);
        let x = MARGIN_SIDE + col_x(col) + (COL_WIDTHS[col] - width) / 2.0;
        let baseline = top - CELL_PAD_V - 9.0 * 0.78;
        page.text(Font::Bold, 9.0, WHITE, x, baseline, label);
    }

    // Row backgrounds: player > external > alternating grey.
    let mut internal_non_player_idx = 0usize;
    let mut row_top = top - HEADER_ROW_H;
    for (offset, row_idx) in (first_row..end_row).enumerate() {
        let row = &table.rows[row_idx];
        let height = block_heights[offset];
        let bg = if row.mine {
            Some(ROW_PLAYER)
        } else if row.external {
            Some(ROW_EXTERNAL)
        } else {
            internal_non_player_idx += 1;
            if internal_non_player_idx.is_multiple_of(2) {
                Some(ROW_ALT)
            } else {
                None
            }
        };
        if let Some(bg) = bg {
            page.rect_fill(
                bg,
                MARGIN_SIDE,
                row_top - height,
                right - MARGIN_SIDE,
                height,
            );
        }
        row_top -= height;
    }

    // Cell text (after fills so backgrounds never cover glyphs).
    row_top = top - HEADER_ROW_H;
    for (offset, row_idx) in (first_row..end_row).enumerate() {
        let cells = &wrapped[row_idx];
        let height = block_heights[offset];
        for (col, lines) in cells.iter().enumerate() {
            if col == 0 {
                continue;
            }
            let centered = matches!(col, 3..=5);
            for (line_no, line) in lines.iter().enumerate() {
                let baseline = row_top - CELL_PAD_V - 8.0 * 0.78 - line_no as f64 * CELL_LEADING;
                let x = if centered {
                    MARGIN_SIDE
                        + col_x(col)
                        + (COL_WIDTHS[col] - text_width(Font::Regular, 8.0, line)) / 2.0
                } else {
                    MARGIN_SIDE + col_x(col) + CELL_PAD_H
                };
                let color = if col == 3 && dirty_highlight[row_idx] {
                    RED
                } else {
                    BLACK
                };
                page.text(Font::Regular, 8.0, color, x, baseline, line);
            }
        }
        row_top -= height;
    }

    // Grid + header underline.
    let mut y = top;
    for height in std::iter::once(&HEADER_ROW_H).chain(block_heights.iter()) {
        y -= height;
        page.line(GRID, 0.5, MARGIN_SIDE, y, right, y);
    }
    page.line(
        DARK,
        1.5,
        MARGIN_SIDE,
        top - HEADER_ROW_H,
        right,
        top - HEADER_ROW_H,
    );
    let mut x = MARGIN_SIDE;
    page.line(GRID, 0.5, x, top, x, table_bottom);
    for width in COL_WIDTHS {
        x += width;
        page.line(GRID, 0.5, x, top, x, table_bottom);
    }

    renderer.cursor = table_bottom;
}

fn col_x(col: usize) -> f64 {
    COL_WIDTHS[..col].iter().sum()
}

fn build_cover_page(plan: &PdfDocumentPlan) -> Page {
    let mut page = Page::default();
    let mut cursor = CONTENT_TOP - 120.0;

    let draw_centered = |page: &mut Page,
                         cursor: &mut f64,
                         font: Font,
                         size: f64,
                         color: Rgb,
                         s: &str,
                         leading: f64,
                         after: f64| {
        let width = text_width(font, size, s);
        let baseline = *cursor - size * 0.78;
        page.text(font, size, color, (PAGE_W - width) / 2.0, baseline, s);
        *cursor -= leading + after;
    };

    draw_centered(
        &mut page,
        &mut cursor,
        Font::Bold,
        28.0,
        DARK,
        "Forza Motorsport",
        34.0,
        6.0,
    );
    draw_centered(
        &mut page,
        &mut cursor,
        Font::Regular,
        16.0,
        GREY,
        "Best Laps",
        20.0,
        4.0,
    );
    cursor -= 30.0;

    // HRFlowable: 50% width, thickness 2, dark.
    let hr_width = CONTENT_W * 0.5;
    let hr_x = (PAGE_W - hr_width) / 2.0;
    page.line(DARK, 2.0, hr_x, cursor, hr_x + hr_width, cursor);
    cursor -= 20.0;

    draw_centered(
        &mut page,
        &mut cursor,
        Font::Bold,
        18.0,
        DARK,
        &plan.gamertag,
        22.0,
        4.0,
    );

    let now = chrono::Local::now();
    let date_text = format!(
        "{} de {} de {}",
        now.day(),
        MONTHS_PT[(now.month0()) as usize % 12],
        now.year()
    );
    draw_centered(
        &mut page,
        &mut cursor,
        Font::Regular,
        12.0,
        GREY_LIGHT,
        &date_text,
        16.0,
        4.0,
    );

    cursor -= 30.0;
    let stats_text = format!(
        "{} tracks  \u{B7}  {} classes  \u{B7}  {} laps",
        plan.stats.tracks, plan.stats.classes, plan.stats.laps
    );
    draw_centered(
        &mut page,
        &mut cursor,
        Font::Regular,
        11.0,
        GREY,
        &stats_text,
        14.0,
        0.0,
    );

    if plan.external_count > 0 {
        cursor -= 12.0;
        let legend = format!(
            "Includes {} external record(s) \u{2014} \u{25A0} highlighted in blue",
            plan.external_count
        );
        let width = text_width(Font::Regular, 10.0, &legend);
        page.text(
            Font::Regular,
            10.0,
            GREY,
            (PAGE_W - width) / 2.0,
            cursor - 10.0 * 0.78,
            &legend,
        );
    }
    page
}

// ── PDF file serialization ───────────────────────────────────────────────────

/// `dests`: (destination name, ordered page index) for the catalog `/Dests`.
fn write_pdf_file(
    pages: &[Page],
    path: &Path,
    dests: &[(String, usize)],
) -> Result<(), PdfRenderError> {
    let mut objects: Vec<Vec<u8>> = vec![Vec::new()];
    let catalog_id = add_object(&mut objects, b"PLACEHOLDER-CATALOG");
    let pages_id = add_object(&mut objects, b"PLACEHOLDER-PAGES");
    let font_regular = add_object(
        &mut objects,
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    );
    let font_bold = add_object(
        &mut objects,
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    );
    // Footer "TOC" label hotspot: the 7pt label starts at the left edge
    // `PAGE_W - MARGIN_SIDE`, so the rect must COVER the glyphs (the old rect
    // ended exactly where the text began — zero overlap, unclickable label).
    let toc_label_w = text_width(Font::Regular, 7.0, "TOC");
    let toc_x0 = PAGE_W - MARGIN_SIDE - 4.0;
    let toc_x1 = PAGE_W - MARGIN_SIDE + toc_label_w + 6.0;
    let link_annot = add_object(
        &mut objects,
        format!(
            "<< /Type /Annot /Subtype /Link /Rect [{} {} {} {}] /Border [0 0 0] /Dest /toc >>",
            num(toc_x0),
            11.0,
            num(toc_x1),
            21.0
        )
        .as_bytes(),
    );

    let mut page_ids = Vec::new();
    for page in pages {
        // Ops chars are latin-1 code points (WinAnsi bytes); encode 1:1.
        let mut stream =
            format!("<< /Length {} >>\nstream\n", page.ops.chars().count()).into_bytes();
        stream.extend(page.ops.chars().map(|c| c as u8));
        stream.extend_from_slice(b"endstream");
        let content_id = add_object(&mut objects, &stream);
        // Per-page row links (TOC entries) plus the shared footer TOC link.
        let mut annot_refs = vec![format!("{link_annot} 0 R")];
        for link in &page.links {
            let annot_id = add_object(
                &mut objects,
                format!(
                    "<< /Type /Annot /Subtype /Link /Rect [{} {} {} {}] /Border [0 0 0] /Dest /{} >>",
                    num(link.x0),
                    num(link.y0),
                    num(link.x1),
                    num(link.y1),
                    link.dest,
                )
                .as_bytes(),
            );
            annot_refs.push(format!("{annot_id} 0 R"));
        }
        let page_body = format!(
            "<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {} {}] \
             /Resources << /Font << /F1 {font_regular} 0 R /F2 {font_bold} 0 R >> >> \
             /Annots [{}] /Contents {content_id} 0 R >>",
            num(PAGE_W),
            num(PAGE_H),
            annot_refs.join(" "),
        );
        page_ids.push(add_object(&mut objects, page_body.as_bytes()));
    }

    let dest_entries = dests
        .iter()
        .map(|(name, page_idx)| {
            let obj = page_ids[(*page_idx).min(page_ids.len() - 1)];
            format!("/{} [{obj} 0 R /XYZ null {} null]", name, num(PAGE_H))
        })
        .collect::<Vec<_>>()
        .join(" ");
    objects[catalog_id] =
        format!("<< /Type /Catalog /Pages {pages_id} 0 R /Dests << {dest_entries} >> >>")
            .into_bytes();

    let kids = page_ids
        .iter()
        .map(|id| format!("{id} 0 R"))
        .collect::<Vec<_>>()
        .join(" ");
    objects[pages_id] = format!(
        "<< /Type /Pages /Kids [{kids}] /Count {} >>",
        page_ids.len()
    )
    .into_bytes();

    let mut pdf = b"%PDF-1.4\n%\xE2\xE3\xCF\xD3\n".to_vec();
    let mut offsets = vec![0usize];
    for (index, object) in objects.iter().enumerate().skip(1) {
        offsets.push(pdf.len());
        pdf.extend_from_slice(format!("{index} 0 obj\n").as_bytes());
        pdf.extend_from_slice(object);
        pdf.extend_from_slice(b"\nendobj\n");
    }
    let xref = pdf.len();
    pdf.extend_from_slice(format!("xref\n0 {}\n", objects.len()).as_bytes());
    pdf.extend_from_slice(b"0000000000 65535 f \n");
    for offset in offsets.iter().skip(1) {
        pdf.extend_from_slice(format!("{offset:010} 00000 n \n").as_bytes());
    }
    pdf.extend_from_slice(
        format!(
            "trailer\n<< /Size {} /Root {catalog_id} 0 R >>\nstartxref\n{xref}\n%%EOF\n",
            objects.len()
        )
        .as_bytes(),
    );

    std::fs::write(path, pdf).map_err(|e| PdfRenderError::Io(e.to_string()))?;
    Ok(())
}

fn add_object(objects: &mut Vec<Vec<u8>>, body: &[u8]) -> usize {
    objects.push(body.to_vec());
    objects.len() - 1
}
