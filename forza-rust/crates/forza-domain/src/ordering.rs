//! Shared ordering keys for best laps across PDF, CSV, and GUI views.

use std::collections::HashMap;

use crate::race_class::class_order;

/// Minimal lap-row projection shared by ordering and frontier calculation.
///
/// One trait (not one per consumer): every lap row — `BestLapRow`,
/// repository exports, test rows — implements this, and both
/// [`ordered_lap_key`] and the frontier functions take `&impl LapRow`.
/// SQLite/CSV/Slint edges keep their own `String` DTOs and convert once.
pub trait LapRow {
    fn id(&self) -> &str;
    fn image_file_id(&self) -> &str;
    fn track(&self) -> &str;
    fn race_class(&self) -> &str;
    fn weather(&self) -> Option<&str>;
    fn temp_f(&self) -> Option<f64>;
    fn driver(&self) -> &str;
    fn car(&self) -> &str;
    fn best_lap_ms(&self) -> i64;
    fn dirty(&self) -> bool;
}

impl<T: LapRow + ?Sized> LapRow for &T {
    fn id(&self) -> &str {
        (**self).id()
    }
    fn image_file_id(&self) -> &str {
        (**self).image_file_id()
    }
    fn track(&self) -> &str {
        (**self).track()
    }
    fn race_class(&self) -> &str {
        (**self).race_class()
    }
    fn weather(&self) -> Option<&str> {
        (**self).weather()
    }
    fn temp_f(&self) -> Option<f64> {
        (**self).temp_f()
    }
    fn driver(&self) -> &str {
        (**self).driver()
    }
    fn car(&self) -> &str {
        (**self).car()
    }
    fn best_lap_ms(&self) -> i64 {
        (**self).best_lap_ms()
    }
    fn dirty(&self) -> bool {
        (**self).dirty()
    }
}

/// Case-insensitive order map based on the canonical track file.
#[must_use]
pub fn track_order_map(track_order: &[String]) -> HashMap<String, usize> {
    track_order
        .iter()
        .enumerate()
        .map(|(index, track)| (track.to_lowercase(), index))
        .collect()
}

#[must_use]
pub fn track_order_key(track: &str, order_map: &HashMap<String, usize>) -> (usize, String) {
    let normalized = track.trim();
    let fallback = order_map.len() + 1;
    let lowered = normalized.to_lowercase();
    (
        order_map.get(lowered.as_str()).copied().unwrap_or(fallback),
        lowered,
    )
}

#[must_use]
pub fn class_order_key(race_class: &str) -> (u32, String) {
    let normalized = race_class.trim();
    (class_order(normalized), normalized.to_string())
}

/// Shared best-lap ordering: track, class, weather, integer milliseconds,
/// driver, car. Integer milliseconds are the domain contract; float seconds
/// are not suitable for equality/frontier rules.
///
/// Ordering rule: SQL pre-sorts cheaply (existing indexes), Rust decides.
/// Consumers must sort with this key as the final authority — SQL `ORDER BY`
/// spellings across repositories exist only to bound result sets, never to
/// define display order.
pub fn ordered_lap_key(
    row: &impl LapRow,
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

    impl LapRow for Row {
        fn id(&self) -> &str {
            ""
        }
        fn image_file_id(&self) -> &str {
            ""
        }
        fn track(&self) -> &str {
            self.track
        }
        fn race_class(&self) -> &str {
            self.class
        }
        fn weather(&self) -> Option<&str> {
            self.weather
        }
        fn temp_f(&self) -> Option<f64> {
            None
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
        fn dirty(&self) -> bool {
            false
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
