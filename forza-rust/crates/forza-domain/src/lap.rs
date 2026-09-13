//! Lap-time parsing/formatting and per-lap domain rules.

use std::collections::HashSet;
use std::sync::LazyLock;

use regex::Regex;
use unicode_general_category::{GeneralCategory, get_general_category};
use unicode_normalization::UnicodeNormalization;

use crate::errors::DomainError;

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

/// GT2 division liveries (in-game names as read by the model; reference
/// source uses longer official names, e.g. "BMW 1 BMW M Motorsport M8 GTE").
/// Observed spec PIs: Vantage GTE 822, M8 838, M6 813, C7 804, C8 821,
/// Viper 808, 488 835, Ford GT 820, 91 RSR 806, 92 RSR 811 (all R).
pub const GT2_CARS: &[&str] = &[
    "#97 Vantage GTE",
    "BMW #1 M8",
    "BMW #24 M6",
    "Chev. #3 C7",
    "Chev. #3 C8",
    "Dodge #93 Viper",
    "Ferrari #62 488",
    "Ford #66 GT",
    "Porsche #91 RSR",
    "Porsche #92 RSR",
];

/// GT3 division liveries (in-game names; e.g. "BMW 96 Turner Motorsports
/// M4 GT3" reference). Observed spec PIs: Vantage 833, AMG GT3 817,
/// 911 GT3 R 820, RC F 784 (S!), M4 GT3 838, Bentley 819, R8 LMS 828,
/// 720S 806, Mustang GT3 829, F458 805, NSX 819, ATS 824, 73 GT3 801.
pub const GT3_CARS: &[&str] = &[
    "AM #7 Vantage",
    "M-AMG GT3",
    "911 GT3 R '23",
    "Lexus #14 RC F",
    "#96 BMW M4 GT3",
    "Bentley #17 C",
    "Audi #44 R8 LMS",
    "McLaren #03 720S",
    "Ford Mustang GT3",
    "#62 F458 GTC",
    "Acura #36 NSX",
    "Cadillac #3 ATS",
    "Porsche #73 GT3",
];

static GT2_CAR_SET: LazyLock<HashSet<&'static str>> =
    LazyLock::new(|| GT2_CARS.iter().copied().collect());

static GT3_CAR_SET: LazyLock<HashSet<&'static str>> =
    LazyLock::new(|| GT3_CARS.iter().copied().collect());

/// Share of the grid that makes a division call (same bar as TCR).
const DIVISION_SHARE: f64 = 0.30;

/// Canonical label for unrecognized/missing weather. Shared with
/// `frontier::condition_key` so grouping and correction agree (ordering keys
/// intentionally keep `""` for missing weather — Python parity, pinned by
/// `ordering_keys_match_python`).
pub const UNKNOWN_WEATHER: &str = "unknown";

static DIRTY_TRAILING: LazyLock<Regex> = lazy_regex!(r"\s*[▲⚠!△†]+\s*$");

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
        // NOTE: no `< 60` seconds guard here on purpose — Python
        // `domain/lap.py` shares the same regex without a range check, and
        // forking the two parsers would split lap identity/review keys
        // between implementations. A joint Python+Rust range rule is future
        // work, not a Rust-only fix.
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
        // Python parity: a name made entirely of stripped symbols round-trips
        // unchanged (golden: "★☆♪" -> "★☆♪"). Changing this would fork
        // frontier identity between the two implementations.
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
        _ => UNKNOWN_WEATHER,
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
/// 1. `>= 30%` TCR liveries → `TCR`.
/// 2. Division check: GT2/GT3 roster shares (same 30% bar) — a single
///    division wins, two sharing the grid → `Mixed`.
/// 3. Multiple PI letters → `Mixed`.
/// 4. Single letter → it.
/// 5. Otherwise `Unknown`.
///
/// The division check runs on car identity, not PI letters, so a GT3 field
/// with an odd letter out (e.g. a PI 784 S car among R cars) still resolves
/// to its division instead of `Mixed`.
pub fn detect_race_class(raw_entries: &[RawGridEntry]) -> String {
    if raw_entries.is_empty() {
        return "Unknown".to_string();
    }

    let mut tcr_count: usize = 0;
    let mut gt2_count: usize = 0;
    let mut gt3_count: usize = 0;
    let mut letters: HashSet<String> = HashSet::new();

    for entry in raw_entries {
        let car = entry.ca.trim();
        let cl = entry.cl.trim();
        if TCR_CAR_SET.contains(car) {
            tcr_count += 1;
        }
        if GT2_CAR_SET.contains(car) {
            gt2_count += 1;
        }
        if GT3_CAR_SET.contains(car) {
            gt3_count += 1;
        }
        let letter = extract_class_letter(Some(cl));
        if letter != "Unknown" {
            letters.insert(letter);
        }
    }

    let total = raw_entries.len() as f64;
    if tcr_count as f64 / total >= DIVISION_SHARE {
        return "TCR".to_string();
    }
    let gt2 = gt2_count as f64 / total >= DIVISION_SHARE;
    let gt3 = gt3_count as f64 / total >= DIVISION_SHARE;
    match (gt2, gt3) {
        (true, false) => return "GT2".to_string(),
        (false, true) => return "GT3".to_string(),
        (true, true) => return "Mixed".to_string(),
        (false, false) => {}
    }
    if letters.len() > 1 {
        return "Mixed".to_string();
    }
    letters
        .into_iter()
        .next()
        .unwrap_or_else(|| "Unknown".to_string())
}

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use super::*;

    #[test]
    fn dagger_is_a_dirty_symbol_like_config_default() {
        // `dirty_lap_symbol` defaults to † (U+2020) in both Python and Rust
        // configs, and exports write it: parsing must round-trip it.
        assert!(is_dirty_lap(Some("1:32.500 †")));
        assert_eq!(strip_dirty_symbol("1:32.500 †"), "1:32.500");
        assert_eq!(parse_lap_time_ms(Some("1:32.500 †")), Some(92_500));
    }

    #[test]
    fn unknown_weather_has_one_shared_spelling() {
        assert_eq!(normalize_weather(None), UNKNOWN_WEATHER);
        assert_eq!(normalize_weather(Some("storm")), UNKNOWN_WEATHER);
    }

    fn grid(rows: &[(&str, &str)]) -> Vec<RawGridEntry> {
        rows.iter()
            .map(|(ca, cl)| RawGridEntry {
                ca: ca.to_string(),
                cl: cl.to_string(),
            })
            .collect()
    }

    #[test]
    fn division_call_by_roster_share_like_tcr() {
        // Pure GT3 field, all letters R: division wins over the letter.
        let gt3 = grid(&[
            ("M-AMG GT3", "PI 817 R"),
            ("AM #7 Vantage", "PI 833 R"),
            ("911 GT3 R '23", "PI 820 R"),
        ]);
        assert_eq!(detect_race_class(&gt3), "GT3");
        // Pure GT2 field reading R is GT2, not R.
        let gt2 = grid(&[
            ("BMW #1 M8", "PI 838 R"),
            ("Porsche #91 RSR", "PI 806 R"),
            ("Ford #66 GT", "PI 820 R"),
        ]);
        assert_eq!(detect_race_class(&gt2), "GT2");
        // GT3 field with an odd S letter out still resolves GT3, not Mixed.
        let mut mixed_letters = gt3.clone();
        mixed_letters.push(RawGridEntry {
            ca: "Lexus #14 RC F".to_string(),
            cl: "PI 784 S".to_string(),
        });
        assert_eq!(detect_race_class(&mixed_letters), "GT3");
        // Two divisions sharing the grid stay Mixed.
        let both = grid(&[
            ("BMW #1 M8", "PI 838 R"),
            ("Porsche #91 RSR", "PI 806 R"),
            ("M-AMG GT3", "PI 817 R"),
            ("AM #7 Vantage", "PI 833 R"),
        ]);
        assert_eq!(detect_race_class(&both), "Mixed");
        // Below the share bar the letters decide again.
        let lone = grid(&[
            ("M-AMG GT3", "PI 817 R"),
            ("Some Road Car", "PI 800 R"),
            ("Other Road Car", "PI 810 R"),
            ("Fourth Road Car", "PI 820 R"),
            ("Fifth Road Car", "PI 830 R"),
        ]);
        assert_eq!(detect_race_class(&lone), "R");
        // TCR keeps priority over divisions.
        let tcr = grid(&[
            ("Honda #73 Civic", "PI 400 D"),
            ("M-AMG GT3", "PI 817 R"),
            ("Some Road Car", "PI 800 R"),
        ]);
        assert_eq!(detect_race_class(&tcr), "TCR");
    }
}
