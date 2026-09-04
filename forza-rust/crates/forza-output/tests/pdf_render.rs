// Test harness: unwraps are idiomatic assertion helpers here.
#![allow(clippy::unwrap_used, clippy::expect_used)]

//! Full PDF renderer: cover page, TOC with link destination, styled track
//! sections, footer page numbers, archiving, and used-files bookkeeping.

use std::path::Path;

use forza_output::csv::ExportRow;
use forza_output::{
    PdfExternalRecord, PdfRenderOptions, build_pdf_plan, build_pdf_plan_ext, render_pdf,
};

fn synthetic_rows() -> Vec<ExportRow> {
    vec![
        ExportRow {
            track: "Fuji Speedway".into(),
            race_class: "A".into(),
            weather: Some("dry".into()),
            temp_c: Some(26.7),
            driver: "TestDriver".into(),
            car: "Audi R8 LMS".into(),
            best_lap: Some("1:32.500".into()),
            best_lap_ms: Some(92_500),
            dirty: false,
            source_file: Some("shot_a.png".into()),
            ..Default::default()
        },
        ExportRow {
            track: "Fuji Speedway".into(),
            race_class: "A".into(),
            weather: Some("rain".into()),
            temp_c: Some(21.0),
            driver: "Rival".into(),
            car: "BMW M4 GT3".into(),
            best_lap: Some("1:33.111".into()),
            best_lap_ms: Some(93_111),
            dirty: true,
            source_file: Some("shot_b.png".into()),
            ..Default::default()
        },
        ExportRow {
            track: "Maple Valley".into(),
            race_class: "B".into(),
            weather: Some("dry".into()),
            temp_c: None,
            driver: "Other".into(),
            car: "Porsche 911 GT3 R".into(),
            best_lap: Some("1:48.900".into()),
            best_lap_ms: Some(108_900),
            dirty: false,
            source_file: Some("shot_c.png".into()),
            ..Default::default()
        },
    ]
}

fn pdf_text(bytes: &[u8]) -> String {
    // Content streams are latin-1 encoded; decode lossily for assertions.
    bytes.iter().map(|&b| b as char).collect()
}

#[test]
fn pdf_renders_cover_toc_sections_and_footer() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("report.pdf");
    let plan = build_pdf_plan(&synthetic_rows(), "TestDriver", &[]);
    let used = render_pdf(&plan, &path).unwrap();

    let bytes = std::fs::read(&path).unwrap();
    let text = pdf_text(&bytes);

    // Structure: header, catalog with named TOC destination, link annotation.
    assert!(bytes.starts_with(b"%PDF-1.4"));
    assert!(text.contains("/Type /Catalog"));
    assert!(text.contains("/Dest /toc"));
    assert!(text.contains("/BaseFont /Helvetica-Bold"));

    // Cover page content.
    assert!(text.contains("(Forza Motorsport) Tj"));
    assert!(text.contains("(Best Laps) Tj"));
    assert!(text.contains("(TestDriver) Tj"));
    // Stats summary.
    assert!(text.contains("2 tracks"));
    assert!(text.contains("3 laps"));

    // TOC page + entries with page numbers.
    assert!(text.contains("(Track Index) Tj"));
    assert!(text.contains("(Fuji Speedway) Tj"));
    assert!(text.contains("(Maple Valley) Tj"));

    // Class table headers and the class colour fill (A = #992800).
    assert!(text.contains("(Driver) Tj"));
    assert!(text.contains("(Best Lap) Tj"));
    assert!(
        text.contains("0.6 0.16 0 rg"),
        "class A colour fill missing"
    );
    // Player row highlight + alternating row.
    assert!(text.contains("1 0.97 0.86 rg"), "player row fill missing");

    // Footer page numbers (cover = page 1).
    assert!(text.contains("Page 1"));
    assert!(text.contains("Page 2"));

    // used_files only contains source files of internal rows.
    assert_eq!(
        used,
        ["shot_a.png", "shot_b.png", "shot_c.png"]
            .into_iter()
            .map(String::from)
            .collect()
    );
}

#[test]
fn pdf_dirty_lap_gets_red_symbol_when_enabled() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("dirty.pdf");
    let plan = build_pdf_plan(&synthetic_rows(), "TestDriver", &[]);
    render_pdf(&plan, &path).unwrap();
    let text = pdf_text(&std::fs::read(&path).unwrap());

    // Dirty time cell rendered in red (#E74C3C) with the symbol appended;
    // the symbol itself is stripped from the clean value.
    assert!(
        text.contains("0.91 0.3 0.24 rg"),
        "red dirty-lap highlight missing"
    );
    assert!(
        text.contains("(1:33.111 \u{0086}) Tj"),
        "dirty symbol must render via WinAnsi dagger"
    );

    // With the symbol disabled the cell is clean and black.
    let path2 = dir.path().join("nodirty.pdf");
    let plan2 = build_pdf_plan_ext(
        &synthetic_rows(),
        "TestDriver",
        &[],
        &[],
        PdfRenderOptions {
            show_dirty_symbol: false,
            dirty_symbol: "\u{2020}".into(),
        },
    );
    render_pdf(&plan2, &path2).unwrap();
    let text2 = pdf_text(&std::fs::read(&path2).unwrap());
    assert!(
        text2.contains("(1:33.111) Tj"),
        "clean time without symbol must be present"
    );
}

#[test]
fn pdf_external_records_render_and_legend_shows() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("external.pdf");
    let externals = vec![PdfExternalRecord {
        track: "Maple Valley".into(),
        race_class: "B".into(),
        driver: "WorldRecord".into(),
        car: "McLaren 720S GT3".into(),
        best_lap: "1:47.500".into(),
        best_lap_ms: 107_500,
    }];
    let plan = build_pdf_plan_ext(
        &synthetic_rows(),
        "TestDriver",
        &[],
        &externals,
        PdfRenderOptions::default(),
    );
    let used = render_pdf(&plan, &path).unwrap();

    let text = pdf_text(&std::fs::read(&path).unwrap());
    // Legend on the cover (parens are escaped in PDF strings).
    assert!(
        text.contains(r#"(Includes 1 external record\(s\)"#),
        "external legend missing from cover"
    );
    // External row rendered in its class table (fastest, so first row).
    assert!(text.contains("(WorldRecord) Tj"));
    assert!(text.contains("(1:47.500) Tj"));
    // External rows have no source file: used_files unchanged.
    assert_eq!(used.len(), 3);
    // Stats include the external lap.
    assert!(text.contains("4 laps"));
}

#[test]
fn render_pdf_archives_previous_report() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("nested").join("report.pdf");
    let plan = build_pdf_plan(&synthetic_rows(), "TestDriver", &[]);

    render_pdf(&plan, &path).unwrap();
    assert!(path.exists());
    let archive = path.parent().unwrap().join("archive");
    assert!(!archive.exists(), "first render must not archive anything");

    std::thread::sleep(std::time::Duration::from_millis(1100));
    render_pdf(&plan, &path).unwrap();

    let archived: Vec<_> = std::fs::read_dir(&archive).unwrap().collect();
    assert_eq!(archived.len(), 1, "second render archives the first report");
    let name = archived[0]
        .as_ref()
        .unwrap()
        .path()
        .file_name()
        .unwrap()
        .to_string_lossy()
        .into_owned();
    assert!(name.starts_with("report_"), "{name}");
    assert!(name.ends_with(".pdf"), "{name}");
    assert!(path.exists(), "fresh report replaces the archived one");
}

#[test]
fn toc_entries_link_to_sections_and_footer_rect_covers_label() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("links.pdf");
    let plan = build_pdf_plan(&synthetic_rows(), "TestDriver", &[]);
    render_pdf(&plan, &path).unwrap();
    let text = pdf_text(&std::fs::read(&path).unwrap());

    // One named destination per section plus the TOC itself.
    assert!(text.contains("/sec-0 "), "section 0 destination missing");
    assert!(text.contains("/sec-1 "), "section 1 destination missing");
    // TOC rows carry Link annotations to their sections.
    assert!(text.contains("/Dest /sec-0"), "TOC row 0 has no link");
    assert!(text.contains("/Dest /sec-1"), "TOC row 1 has no link");
    // Footer hotspot must cover the "TOC" glyphs: the 7pt label starts at
    // x = 595-30 = 565, so the rect must extend past 565 (the old rect ended
    // exactly at 565 — zero overlap with the visible text).
    let footer_rect = text
        .find("/Dest /toc")
        .and_then(|i| text[..i].rfind("/Rect ["))
        .map(|i| text[i..i + 40].to_string())
        .unwrap_or_default();
    let right: f64 = footer_rect
        .trim_start_matches("/Rect [")
        .split_whitespace()
        .nth(2)
        .and_then(|n| n.trim_end_matches(']').parse().ok())
        .unwrap_or(0.0);
    assert!(
        right > 565.0,
        "footer TOC rect {footer_rect:?} does not cover the label"
    );
}

#[test]
fn empty_plan_writes_nothing_like_python() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("empty.pdf");
    let plan = build_pdf_plan(&[], "TestDriver", &[]);
    let used = render_pdf(&plan, &path).unwrap();
    assert!(used.is_empty());
    assert!(!path.exists());
    let _ = Path::new("unused");
}
