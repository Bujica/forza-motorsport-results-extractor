//! Reference data container plus track/car name correction strategies.

use std::collections::{HashMap, HashSet};

use crate::difflib;
use crate::text_utils;

/// Fuzzy cutoff for track names (Python parity, see `difflib.get_close_matches`).
pub const TRACK_FUZZY_CUTOFF: f64 = 0.75;
/// Fuzzy cutoff for car names (stricter: car catalog is larger).
pub const CAR_FUZZY_CUTOFF: f64 = 0.85;

/// Pre-computed normalized forms of one canonical track name, so
/// [`fix_track_name`] never renormalizes the whole catalog per call
/// (previously O(rows · refs · nfkd_cost)).
#[derive(Debug, Clone)]
struct PreparedTrack {
    lower: String,
    norm: String,
    key: String,
    original: String,
}

/// Reference catalog: canonical track names, car names, and a normalized
/// car key map (normalized key → original name), first occurrence wins.
#[derive(Debug, Clone, Default)]
pub struct ReferenceData {
    pub tracks: Vec<String>,
    pub cars: Vec<String>,
    pub car_map: HashMap<String, String>,
    prepared_tracks: Vec<PreparedTrack>,
    car_values: Vec<String>,
}

impl ReferenceData {
    pub fn from_lines(tracks: Vec<String>, cars: Vec<String>) -> Self {
        let prepared_tracks = tracks
            .iter()
            .map(|t| PreparedTrack {
                lower: t.to_lowercase(),
                norm: normalize(t, true),
                key: track_key(t),
                original: t.clone(),
            })
            .collect();
        let (car_map, car_values) = build_car_map(&cars);
        Self {
            tracks,
            cars,
            car_map,
            prepared_tracks,
            car_values,
        }
    }
}

fn normalize(text: &str, spaces: bool) -> String {
    text_utils::normalize_ascii_compare(text, spaces)
}

fn track_key(text: &str) -> String {
    let norm = normalize(text, true);
    let mut out = String::with_capacity(norm.len());
    let mut pending_sep = false;
    for ch in norm.chars() {
        if ch.is_ascii_lowercase() || ch.is_ascii_digit() {
            if pending_sep {
                out.push(' ');
                pending_sep = false;
            }
            out.push(ch);
        } else {
            pending_sep = !out.is_empty();
        }
    }
    out
}

fn build_car_map(cars: &[String]) -> (HashMap<String, String>, Vec<String>) {
    let mut map: HashMap<String, String> = HashMap::with_capacity(cars.len());
    let mut seen: HashSet<String> = HashSet::with_capacity(cars.len());
    let mut values: Vec<String> = Vec::with_capacity(cars.len());
    for car in cars {
        let key = normalize(car, false);
        if seen.insert(key.clone()) {
            map.insert(key, car.clone());
            values.push(car.clone());
        }
    }
    (map, values)
}

/// Match a raw OCR track name against the reference list.
///
/// Returns `None` only when a prefix match is ambiguous; unrecognised input
/// is returned unchanged so callers can flag it.
pub fn fix_track_name(raw: &str, refs: &ReferenceData) -> Option<String> {
    if raw.is_empty() || refs.tracks.is_empty() {
        return Some(raw.to_string());
    }

    let term: String = raw.split_whitespace().collect::<Vec<_>>().join(" ");
    let term_low = term.to_lowercase();

    // 1) Exact
    for prepared in &refs.prepared_tracks {
        if prepared.lower == term_low {
            return Some(prepared.original.clone());
        }
    }

    // 2) Accent-normalised exact
    let term_norm = normalize(&term, true);
    for prepared in &refs.prepared_tracks {
        if prepared.norm == term_norm {
            return Some(prepared.original.clone());
        }
    }

    // 3) Punctuation-insensitive exact
    let term_key = track_key(&term);
    for prepared in &refs.prepared_tracks {
        if prepared.key == term_key {
            return Some(prepared.original.clone());
        }
    }

    // 4) Prefix match — safe only when unambiguous
    let prefix_matches: Vec<&String> = refs
        .prepared_tracks
        .iter()
        .filter(|t| t.key.starts_with(term_key.as_str()))
        .map(|t| &t.original)
        .collect();
    match prefix_matches.len() {
        1 => return Some(prefix_matches[0].clone()),
        n if n > 1 => return None,
        _ => {}
    }

    // 5) Fuzzy — only when prefix found nothing
    let matches = difflib::get_close_matches(&term, &refs.tracks, 1, TRACK_FUZZY_CUTOFF);
    if let Some(first) = matches.into_iter().next() {
        return Some(first);
    }

    // 6) Unrecognised — unchanged
    Some(term)
}

/// Match a raw OCR car name against the pre-computed car map.
pub fn fix_car_name(raw: &str, refs: &ReferenceData) -> String {
    if raw.is_empty() || refs.car_map.is_empty() {
        return raw.to_string();
    }

    let raw_str = raw.trim();
    let raw_norm = normalize(raw_str, false);
    // A punctuation-only input normalizes to "": `contains("")` would match
    // every key, so bail out early instead of relying on later stages.
    if raw_norm.is_empty() {
        return raw_str.to_string();
    }

    // 1) Exact (O(1) hash lookup, first occurrence wins at build time)
    if let Some(corrected) = refs.car_map.get(&raw_norm) {
        return corrected.clone();
    }

    // 2) Substring (unique only)
    let candidates: Vec<&String> = refs
        .car_map
        .iter()
        .filter(|(k, _)| k.contains(raw_norm.as_str()))
        .map(|(_, v)| v)
        .collect();
    if candidates.len() == 1 {
        return candidates[0].clone();
    }

    // 3) Fuzzy over values in insertion order (no per-call clone)
    if let Some(first) = difflib::get_close_matches(raw_str, &refs.car_values, 1, CAR_FUZZY_CUTOFF)
        .into_iter()
        .next()
    {
        return first;
    }

    raw_str.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn refs() -> ReferenceData {
        ReferenceData::from_lines(
            vec![
                "Fuji Speedway GT".to_string(),
                "Fuji Speedway".to_string(),
                "Nürburgring Nordschleife".to_string(),
                "Le Mans Full Circuit".to_string(),
                "Le Mans Old Mulsanne Circuit".to_string(),
            ],
            vec!["Audi R8 LMS".to_string(), "BMW M4 GT3".to_string()],
        )
    }

    #[test]
    fn exact_and_normalized_track_match() {
        let r = refs();
        assert_eq!(
            fix_track_name("fuji speedway", &r).unwrap(),
            "Fuji Speedway"
        );
        assert_eq!(
            fix_track_name("Nurburgring Nordschleife", &r).unwrap(),
            "Nürburgring Nordschleife"
        );
    }

    #[test]
    fn ambiguous_prefix_returns_none_for_review() {
        let r = refs();
        assert_eq!(fix_track_name("Le Mans", &r), None);
        assert_eq!(
            fix_track_name("Le Mans Full", &r).unwrap(),
            "Le Mans Full Circuit"
        );
    }

    #[test]
    fn punctuation_insensitive_and_unrecognised() {
        let r = refs();
        assert_eq!(
            fix_track_name("nürburgring  nordschleife!", &r).unwrap(),
            "Nürburgring Nordschleife"
        );
        assert_eq!(
            fix_track_name("Totally Unknown Track", &r).unwrap(),
            "Totally Unknown Track"
        );
    }

    #[test]
    fn car_exact_normalised_match_is_case_insensitive_no_spaces() {
        let r = refs();
        assert_eq!(fix_car_name("audi r8 lms", &r), "Audi R8 LMS");
        assert_eq!(fix_car_name("audir8lms", &r), "Audi R8 LMS");
        assert_eq!(fix_car_name("Unknown Car", &r), "Unknown Car");
    }

    #[test]
    fn punctuation_only_input_never_matches_single_car_catalog() {
        let r = ReferenceData::from_lines(vec![], vec!["Audi R8 LMS".to_string()]);
        assert_eq!(fix_car_name("---", &r), "---");
        assert_eq!(fix_car_name("...", &r), "...");
    }
}
