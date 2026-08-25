//! Lap-time parsing/formatting and per-lap domain rules.

use std::collections::HashSet;
use std::sync::LazyLock;

use regex::Regex;
use unicode_general_category::{GeneralCategory, get_general_category};
use unicode_normalization::UnicodeNormalization;

use crate::errors::DomainError;

/// Compile-once regex; patterns here are static and infallible.
macro_rules! lazy_regex {
    ($pattern:expr) => {
        LazyLock::new(|| match Regex::new($pattern) {
            Ok(re) => re,
            Err(err) => panic!("invalid built-in regex: {err}"),
        })
    };
}

/// TCR livery names; a race where >= 30% of the grid drives one is TCR.
pub const TCR_CARS: &[&str] = &[
    "MG #20 MG6",
    "VW #22 Golf GTI",
    "#66 Astra",
    "#98 Veloster",
    "SUBARU #1 Levorg",
    "Lynk #100 03",
    "Audi #1 RS 3 LMS",
    "Peugeot #7 308",
    "#98 Elantra",
    "Honda #73 Civic",
    "Ford #17Focus ST",
    "MB #33 A45",
];

static TCR_CAR_SET: LazyLock<HashSet<&'static str>> =
    LazyLock::new(|| TCR_CARS.iter().copied().collect());

static DIRTY_TRAILING: LazyLock<Regex> = lazy_regex!(r"\s*[▲⚠!△]+\s*$");

static VARIATION_SELECTORS: LazyLock<Regex> = lazy_regex!("[\u{FE00}-\u{FE0F}]");

/// Remove variation selectors so ⚠️ (U+26A0 U+FE0F) matches plain ⚠.
fn remove_variation_selectors(value: &str) -> String {
    VARIATION_SELECTORS.replace_all(value, "").into_owned()
}

/// Remove trailing dirty-lap symbol(s) and preceding whitespace. Symbols in
/// the middle or beginning are preserved.
pub fn strip_dirty_symbol(value: &str) -> String {
    let s = value.trim();
    let s = remove_variation_selectors(s);
    DIRTY_TRAILING.replace_all(&s, "").into_owned()
}

const LAP_TIME_PLACEHOLDERS: &[&str] = &["", "--", "---", "dnf", "dnq", "null", "none"];

/// Convert a lap time string (`MM:SS.mmm` or `SS.mmm`) to canonical integer
/// milliseconds. Gap times, placeholders, and invalid values return `None`.
pub fn parse_lap_time_ms(value: Option<&str>) -> Option<i64> {
    let raw = value?.trim();
    if LAP_TIME_PLACEHOLDERS.contains(&raw.to_lowercase().as_str()) {
        return None;
    }
    if raw.contains('+') {
        return None;
    }

    let clean = strip_dirty_symbol(raw);

    static MM_SS: LazyLock<Regex> = lazy_regex!(r"^(\d+):(\d{2})(?:\.(\d{1,3}))?$");
    static SS_ONLY: LazyLock<Regex> = lazy_regex!(r"^(\d{1,2})(?:\.(\d{1,3}))?$");

    if let Some(m) = MM_SS.captures(&clean) {
        let frac = fraction_ms(m.get(3).map(|g| g.as_str()));
        let minutes: i64 = m[1].parse().ok()?;
        let seconds: i64 = m[2].parse().ok()?;
        return Some((minutes * 60 + seconds) * 1000 + frac);
    }

    if let Some(m) = SS_ONLY.captures(&clean) {
        let frac = fraction_ms(m.get(2).map(|g| g.as_str()));
        let seconds: i64 = m[1].parse().ok()?;
        return Some(seconds * 1000 + frac);
    }

    None
}

fn fraction_ms(group: Option<&str>) -> i64 {
    let raw = group.unwrap_or("0");
    let digits: Vec<u32> = raw.chars().take(3).filter_map(|c| c.to_digit(10)).collect();
    match digits.as_slice() {
        [] => 0,
        [d] => (*d * 100) as i64,
        [d1, d2] => (*d1 * 100 + *d2 * 10) as i64,
        [d1, d2, d3] => (*d1 * 100 + *d2 * 10 + d3) as i64,
        _ => 0,
    }
}

/// Format canonical integer milliseconds as `M:SS.mmm`, optionally with the
/// trailing dirty marker used by exports.
pub fn format_lap_time_ms(value: i64, dirty: bool) -> Result<String, DomainError> {
    if value <= 0 {
        return Err(DomainError::NonPositiveLapTime);
    }
    let total_seconds = value / 1000;
    let ms = value % 1000;
    let minutes = total_seconds / 60;
    let seconds = total_seconds % 60;
    let suffix = if dirty { " ▲" } else { "" };
    Ok(format!("{minutes}:{seconds:02}.{ms:03}{suffix}"))
}

/// True when the lap-time string ends with a dirty-lap symbol, optionally
/// preceded by whitespace.
pub fn is_dirty_lap(value: Option<&str>) -> bool {
    let s = remove_variation_selectors(value.unwrap_or("").trim());
    DIRTY_TRAILING.is_match(&s)
}

/// Remove visual badges/icons while keeping common gamertag characters.
pub fn sanitize_driver_name(value: Option<&str>) -> String {
    let normalized: String = value.unwrap_or("").nfkc().collect();
    let text = remove_variation_selectors(normalized.trim());

    let mut chars: Vec<char> = Vec::with_capacity(text.len());
    for ch in text.chars() {
        if ch.is_alphanumeric() || matches!(ch, ' ' | '_' | '-' | '.' | '\'') {
            chars.push(ch);
        } else if matches!(
            get_general_category(ch),
            GeneralCategory::NonspacingMark
                | GeneralCategory::SpacingMark
                | GeneralCategory::EnclosingMark
        ) {
            continue;
        } else if ch.is_whitespace() {
            chars.push(' ');
        }
    }

    let mut clean = String::from_iter(chars);
    clean = collapse_whitespace(&clean);
    let trimmed = clean.trim_matches(|c| matches!(c, ' ' | '.' | '_' | '-'));
    let trimmed = trimmed.to_string();
    if trimmed.is_empty() {
        text.to_string()
    } else {
        trimmed
    }
}

fn collapse_whitespace(value: &str) -> String {
    let mut out = String::with_capacity(value.len());
    let mut pending_space = false;
    for ch in value.chars() {
        if ch.is_whitespace() {
            if !out.is_empty() {
                pending_space = true;
            }
        } else {
            if pending_space {
                out.push(' ');
                pending_space = false;
            }
            out.push(ch);
        }
    }
    out
}

/// Map model/weather words (English and Portuguese) onto the supported labels.
pub fn normalize_weather(value: Option<&str>) -> &'static str {
    let text = value.unwrap_or("").trim().to_lowercase();
    match text.as_str() {
        "rain" | "wet" | "chuva" | "molhado" | "raining" => "rain",
        "dry" | "seco" | "clear" | "sunny" => "dry",
        _ => "unknown",
    }
}

/// Convert °F to °C rounded to one decimal, validated against a plausible
/// track-temperature window. Returns `None` outside `[temp_min, temp_max]`.
pub fn fahrenheit_to_celsius(tf: f64, temp_min: f64, temp_max: f64) -> Option<f64> {
    if (temp_min..=temp_max).contains(&tf) {
        Some(((tf - 32.0) * 5.0 / 9.0 * 10.0).round() / 10.0)
    } else {
        None
    }
}

/// String-typed variant accepting comma decimal separators like the model's
/// textual temperature output.
pub fn fahrenheit_to_celsius_str(tf: Option<&str>, temp_min: f64, temp_max: f64) -> Option<f64> {
    let raw = tf?;
    let normalized = raw.trim().replace(',', ".");
    let val: f64 = normalized.parse().ok()?;
    fahrenheit_to_celsius(val, temp_min, temp_max)
}

/// Extract the single class letter from the LLM's `cl` field.
///
/// Handles `"692 A"`, `"692A"`, `"PI400D"` and bare letters; anything else is
/// `"Unknown"`.
pub fn extract_class_letter(cl_field: Option<&str>) -> String {
    let s = cl_field.unwrap_or("").trim().to_uppercase();
    if s.is_empty() {
        return "Unknown".to_string();
    }

    static BARE_LETTER: LazyLock<Regex> = lazy_regex!(r"^[A-Z]$");
    static CONCATENATED: LazyLock<Regex> = lazy_regex!(r"^(?:PI)?\d+[A-Z]$");

    let last = s.split_whitespace().next_back().unwrap_or_default();
    if BARE_LETTER.is_match(last) {
        return last.to_string();
    }
    if CONCATENATED.is_match(last) {
        return last.chars().last().unwrap_or('U').to_string();
    }
    "Unknown".to_string()
}

/// One grid row as delivered by the model (`ca` = car, `cl` = class field).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RawGridEntry {
    pub ca: String,
    pub cl: String,
}

/// Determine race class for a grid of corrected-car entries.
///
/// 1. >= 30% TCR liveries → `TCR`; 2. multiple letters → `Mixed`;
/// 3. single letter → it; 4. otherwise `Unknown`.
pub fn detect_race_class(raw_entries: &[RawGridEntry]) -> String {
    if raw_entries.is_empty() {
        return "Unknown".to_string();
    }

    let mut tcr_count: usize = 0;
    let mut letters: HashSet<String> = HashSet::new();

    for entry in raw_entries {
        let car = entry.ca.trim();
        let cl = entry.cl.trim();
        if TCR_CAR_SET.contains(car) {
            tcr_count += 1;
        }
        let letter = extract_class_letter(Some(cl));
        if letter != "Unknown" {
            letters.insert(letter);
        }
    }

    if tcr_count as f64 / raw_entries.len() as f64 >= 0.30 {
        return "TCR".to_string();
    }
    if letters.len() > 1 {
        return "Mixed".to_string();
    }
    letters
        .into_iter()
        .next()
        .unwrap_or_else(|| "Unknown".to_string())
}
