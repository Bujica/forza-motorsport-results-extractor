//! Shared ordering keys for best laps across PDF, CSV, and GUI views.

use std::collections::HashMap;

use crate::race_class::class_order;

/// Minimal row projection required for lap ordering.
pub trait LapRowLike {
    fn track(&self) -> &str;
    fn race_class(&self) -> &str;
    fn weather(&self) -> Option<&str>;
    fn best_lap_ms(&self) -> i64;
    fn driver(&self) -> &str;
    fn car(&self) -> &str;
}

/// Case-insensitive order map based on the canonical track file.
pub fn track_order_map(track_order: &[String]) -> HashMap<String, usize> {
    track_order
        .iter()
        .enumerate()
        .map(|(index, track)| (track.to_lowercase(), index))
        .collect()
}

pub fn track_order_key(track: &str, order_map: &HashMap<String, usize>) -> (usize, String) {
    let normalized = track.trim();
    let fallback = order_map.len() + 1;
    (
        order_map
            .get(normalized.to_lowercase().as_str())
            .copied()
            .unwrap_or(fallback),
        normalized.to_lowercase(),
    )
}

pub fn class_order_key(race_class: &str) -> (u32, String) {
    let normalized = race_class.trim();
    (class_order(normalized), normalized.to_string())
}

/// Shared best-lap ordering: track, class, weather, integer milliseconds,
/// driver, car. Integer milliseconds are the domain contract; float seconds
/// are not suitable for equality/frontier rules.
pub fn ordered_lap_key(
    row: &impl LapRowLike,
    order_map: &HashMap<String, usize>,
) -> (usize, String, u32, String, String, i64, String, String) {
    let (t_rank, t_name) = track_order_key(row.track(), order_map);
    let (c_rank, c_name) = class_order_key(row.race_class());
    (
        t_rank,
        t_name,
        c_rank,
        c_name,
        row.weather().unwrap_or("").to_lowercase(),
        row.best_lap_ms(),
        row.driver().to_lowercase(),
        row.car().to_lowercase(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Row {
        track: &'static str,
        class: &'static str,
        weather: Option<&'static str>,
        ms: i64,
        driver: &'static str,
        car: &'static str,
    }

    impl LapRowLike for Row {
        fn track(&self) -> &str {
            self.track
        }
        fn race_class(&self) -> &str {
            self.class
        }
        fn weather(&self) -> Option<&str> {
            self.weather
        }
        fn best_lap_ms(&self) -> i64 {
            self.ms
        }
        fn driver(&self) -> &str {
            self.driver
        }
        fn car(&self) -> &str {
            self.car
        }
    }

    #[test]
    fn unknown_tracks_sort_after_known_ones() {
        let order: Vec<String> = vec![
            "Fuji Speedway".to_string(),
            "Le Mans Full Circuit".to_string(),
        ];
        let map = track_order_map(&order);
        let known = Row {
            track: "Fuji Speedway",
            class: "A",
            weather: Some("dry"),
            ms: 90_000,
            driver: "d",
            car: "c",
        };
        let unknown = Row {
            track: "Mystery",
            class: "A",
            weather: Some("dry"),
            ms: 80_000,
            driver: "d",
            car: "c",
        };
        assert!(ordered_lap_key(&known, &map) < ordered_lap_key(&unknown, &map));
    }

    #[test]
    fn class_and_time_dominate_ordering() {
        let map = track_order_map(&[]);
        let faster = Row {
            track: "X",
            class: "B",
            weather: None,
            ms: 60_000,
            driver: "a",
            car: "c",
        };
        let slower_higher_class = Row {
            track: "X",
            class: "A",
            weather: None,
            ms: 90_000,
            driver: "a",
            car: "c",
        };
        assert!(ordered_lap_key(&faster, &map) < ordered_lap_key(&slower_higher_class, &map));
    }
}
