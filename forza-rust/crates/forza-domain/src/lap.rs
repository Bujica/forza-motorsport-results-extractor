//! Lap-time parsing/formatting and per-lap domain rules.

use std::collections::HashSet;
use std::sync::LazyLock;

use regex::Regex;
use unicode_general_category::{GeneralCategory, get_general_category};
use unicode_normalization::UnicodeNormalization;

use crate::enums::{RaceClass, WeatherType};
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

/// Division roster table: adding a future division (e.g. `GTA`) is one entry
/// here plus the `RaceClass` arms — no new counter, set, or match arm in
/// [`detect_race_class`].
const DIVISIONS: &[(RaceClass, &[&str])] = &[
    (RaceClass::Tcr, TCR_CARS),
    (RaceClass::Gt2, GT2_CARS),
    (RaceClass::Gt3, GT3_CARS),
];

/// Car livery → division class. First roster wins on overlap (rosters are
/// asserted disjoint in tests, so this is a backstop, not a rule).
static DIVISION_BY_CAR: LazyLock<std::collections::HashMap<&'static str, RaceClass>> =
    LazyLock::new(|| {
        let mut map = std::collections::HashMap::new();
        for (class, roster) in DIVISIONS {
            for car in *roster {
                map.entry(*car).or_insert(*class);
            }
        }
        map
    });

/// Share of the grid that makes a division call (same bar as TCR).
const DIVISION_SHARE: f64 = 0.30;

/// Canonical label for unrecognized/missing weather. Shared with
/// `frontier::condition_key` so grouping and correction agree (ordering keys
/// intentionally keep `""` for missing weather — Python parity, pinned by
/// `ordering_keys_match_python`).
pub const UNKNOWN_WEATHER: &str = "unknown";

/// Canonical dirty-mark set (Python parity). Single owner: the trailing
/// matcher below, [`strip_dirty_symbol`], and the doctor `LIKE` pattern in
/// `forza-db/src/doctor/images.rs` all derive from this — never retype the
/// set. This is the *parse* vocabulary (what the model emits); the PDF
/// *render* symbol (`cfg.pdf.dirty_lap_symbol`, default `†`) is independent
/// and lives in `forza-config`.
pub const DEFAULT_DIRTY_SYMBOLS: &str = "▲⚠!△†";

fn dirty_trailing_pattern() -> String {
    let class: String = DEFAULT_DIRTY_SYMBOLS
        .chars()
        .map(|c| regex::escape(&c.to_string()))
        .collect();
    format!(r"\s*[{class}]+\s*$")
}

static DIRTY_TRAILING: LazyLock<Regex> =
    LazyLock::new(|| match Regex::new(&dirty_trailing_pattern()) {
        Ok(re) => re,
        Err(err) => panic!("invalid built-in regex: {err}"),
    });

static VARIATION_SELECTORS: LazyLock<Regex> = lazy_regex!("[\u{FE00}-\u{FE0F}]");

/// Remove variation selectors so ⚠️ (U+26A0 U+FE0F) matches plain ⚠.
fn remove_variation_selectors(value: &str) -> String {
    VARIATION_SELECTORS.replace_all(value, "").into_owned()
}

/// Remove trailing dirty-lap symbol(s) and preceding whitespace. Symbols in
/// the middle or beginning are preserved. Strips [`DEFAULT_DIRTY_SYMBOLS`];
/// the PDF render symbol is configured separately (see the const docs).
#[must_use]
pub fn strip_dirty_symbol(value: &str) -> String {
    let s = value.trim();
    let s = remove_variation_selectors(s);
    DIRTY_TRAILING.replace_all(&s, "").into_owned()
}

const LAP_TIME_PLACEHOLDERS: &[&str] = &["", "--", "---", "dnf", "dnq", "null", "none"];

/// Convert a lap time string (`MM:SS.mmm` or `SS.mmm`) to canonical integer
/// milliseconds. Gap times, placeholders, and invalid values return `None`.
#[must_use]
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

/// True when the lap-time string ends with a dirty-lap symbol
/// ([`DEFAULT_DIRTY_SYMBOLS`]), optionally preceded by whitespace.
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
///
/// Returns the unified [`WeatherType`]; callers bound to text (SQLite,
/// Slint, CSV) convert with [`WeatherType::as_str`].
///
/// # Examples
///
/// ```
/// use forza_domain::enums::WeatherType;
/// use forza_domain::lap::normalize_weather;
///
/// assert_eq!(normalize_weather(Some("chuva")), WeatherType::Rain);
/// assert_eq!(normalize_weather(None), WeatherType::Unknown);
/// ```
pub fn normalize_weather(value: Option<&str>) -> WeatherType {
    let text = value.unwrap_or("").trim().to_lowercase();
    match text.as_str() {
        "rain" | "wet" | "chuva" | "molhado" | "raining" => WeatherType::Rain,
        "dry" | "seco" | "clear" | "sunny" => WeatherType::Dry,
        _ => WeatherType::Unknown,
    }
}

/// No-config fallback plausibility window (°F). Mirrors the `[validation]`
/// `temp_min_f`/`temp_max_f` config defaults; callers with a loaded config
/// pass its values instead of this const.
pub const DEFAULT_TEMP_RANGE_F: (f64, f64) = (40.0, 140.0);

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
/// [`RaceClass::Unknown`].
pub fn extract_class_letter(cl_field: Option<&str>) -> RaceClass {
    let s = cl_field.unwrap_or("").trim().to_uppercase();
    if s.is_empty() {
        return RaceClass::Unknown;
    }

    static BARE_LETTER: LazyLock<Regex> = lazy_regex!(r"^[A-Z]$");
    static CONCATENATED: LazyLock<Regex> = lazy_regex!(r"^(?:PI)?\d+[A-Z]$");

    let last = s.split_whitespace().next_back().unwrap_or_default();
    if BARE_LETTER.is_match(last) {
        return RaceClass::from_value(last).unwrap_or(RaceClass::Unknown);
    }
    if CONCATENATED.is_match(last) {
        let letter = last
            .chars()
            .last()
            .map(|c| c.to_string())
            .unwrap_or_default();
        return RaceClass::from_value(&letter).unwrap_or(RaceClass::Unknown);
    }
    RaceClass::Unknown
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
pub fn detect_race_class(raw_entries: &[RawGridEntry]) -> RaceClass {
    if raw_entries.is_empty() {
        return RaceClass::Unknown;
    }

    let mut division_counts: std::collections::HashMap<RaceClass, usize> =
        std::collections::HashMap::new();
    let mut letters: HashSet<RaceClass> = HashSet::new();

    for entry in raw_entries {
        let car = entry.ca.trim();
        let cl = entry.cl.trim();
        if let Some(class) = DIVISION_BY_CAR.get(car) {
            *division_counts.entry(*class).or_default() += 1;
        }
        let letter = extract_class_letter(Some(cl));
        if letter != RaceClass::Unknown {
            letters.insert(letter);
        }
    }

    let total = raw_entries.len() as f64;
    let share = |class: RaceClass| division_counts.get(&class).copied().unwrap_or(0) as f64 / total;
    // TCR keeps priority over divisions (historical rule, preserved).
    if share(RaceClass::Tcr) >= DIVISION_SHARE {
        return RaceClass::Tcr;
    }
    // Exactly one division over the bar wins; two or more sharing the grid
    // stay Mixed. Generic over DIVISIONS so a future entry needs no new arm.
    let mut winners: Vec<RaceClass> = DIVISIONS
        .iter()
        .map(|(class, _)| *class)
        .filter(|class| *class != RaceClass::Tcr && share(*class) >= DIVISION_SHARE)
        .collect();
    winners.sort_by_key(|class| class.order());
    match winners.as_slice() {
        [single] => return *single,
        [_, _, ..] => return RaceClass::Mixed,
        [] => {}
    }
    if letters.len() > 1 {
        return RaceClass::Mixed;
    }
    letters.into_iter().next().unwrap_or(RaceClass::Unknown)
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
    fn every_dirty_symbol_is_detected_stripped_and_parsed() {
        // Single-owner set: a symbol added to DEFAULT_DIRTY_SYMBOLS is
        // covered by detection, stripping, and parsing with no other change.
        // The config render default (†) must stay a member (see
        // `config_dirty_default_is_parseable` in forza-app).
        assert!(DEFAULT_DIRTY_SYMBOLS.contains('†'));
        for symbol in DEFAULT_DIRTY_SYMBOLS.chars() {
            let text = format!("1:32.500 {symbol}");
            assert!(is_dirty_lap(Some(&text)), "detect {symbol}");
            assert_eq!(strip_dirty_symbol(&text), "1:32.500", "strip {symbol}");
            assert_eq!(
                parse_lap_time_ms(Some(&text)),
                Some(92_500),
                "parse {symbol}"
            );
        }
    }

    #[test]
    fn unknown_weather_has_one_shared_spelling() {
        assert_eq!(normalize_weather(None), WeatherType::Unknown);
        assert_eq!(normalize_weather(Some("storm")), WeatherType::Unknown);
    }

    proptest::proptest! {
        /// Format/parse round-trip over a full day of milliseconds, clean and
        /// dirty: the canonical text form must always decode back.
        #[test]
        fn lap_time_format_parse_round_trip(ms in 0i64..86_400_000, dirty in proptest::bool::ANY) {
            let text = format_lap_time_ms(ms, dirty).unwrap();
            proptest::prop_assert_eq!(parse_lap_time_ms(Some(&text)), Some(ms));
        }
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
        assert_eq!(detect_race_class(&gt3), RaceClass::Gt3);
        // Pure GT2 field reading R is GT2, not R.
        let gt2 = grid(&[
            ("BMW #1 M8", "PI 838 R"),
            ("Porsche #91 RSR", "PI 806 R"),
            ("Ford #66 GT", "PI 820 R"),
        ]);
        assert_eq!(detect_race_class(&gt2), RaceClass::Gt2);
        // GT3 field with an odd S letter out still resolves GT3, not Mixed.
        let mut mixed_letters = gt3.clone();
        mixed_letters.push(RawGridEntry {
            ca: "Lexus #14 RC F".to_string(),
            cl: "PI 784 S".to_string(),
        });
        assert_eq!(detect_race_class(&mixed_letters), RaceClass::Gt3);
        // Two divisions sharing the grid stay Mixed.
        let both = grid(&[
            ("BMW #1 M8", "PI 838 R"),
            ("Porsche #91 RSR", "PI 806 R"),
            ("M-AMG GT3", "PI 817 R"),
            ("AM #7 Vantage", "PI 833 R"),
        ]);
        assert_eq!(detect_race_class(&both), RaceClass::Mixed);
        // Below the share bar the letters decide again.
        let lone = grid(&[
            ("M-AMG GT3", "PI 817 R"),
            ("Some Road Car", "PI 800 R"),
            ("Other Road Car", "PI 810 R"),
            ("Fourth Road Car", "PI 820 R"),
            ("Fifth Road Car", "PI 830 R"),
        ]);
        assert_eq!(detect_race_class(&lone), RaceClass::R);
        // TCR keeps priority over divisions.
        let tcr = grid(&[
            ("Honda #73 Civic", "PI 400 D"),
            ("M-AMG GT3", "PI 817 R"),
            ("Some Road Car", "PI 800 R"),
        ]);
        assert_eq!(detect_race_class(&tcr), RaceClass::Tcr);
    }

    #[test]
    fn division_rosters_are_disjoint() {
        // `DIVISION_BY_CAR` keeps the first roster on overlap; disjoint
        // rosters make that a backstop. A shared livery across divisions
        // must be resolved explicitly, not by map order.
        let mut seen: HashSet<&str> = HashSet::new();
        for (_, roster) in DIVISIONS {
            for car in *roster {
                assert!(seen.insert(car), "livery in two division rosters: {car}");
            }
        }
    }
}
