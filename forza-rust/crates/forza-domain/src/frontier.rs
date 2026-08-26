//! Best-lap frontier calculation. Ported from `forza/db/repositories/frontier.py`.
//!
//! Pure domain logic: no database access. The repository layer feeds rows in
//! and applies winners back.

use std::collections::{HashMap, HashSet};

/// Minimal row projection required by the frontier.
pub trait FrontierLap {
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

#[derive(Debug, Clone, PartialEq)]
pub struct FrontierWinner {
    pub id: String,
    pub image_file_id: String,
}

/// Simple best clean row per (track, class, driver, car).
pub fn simple_best_rows<L>(rows: &[L]) -> Vec<&L>
where
    L: FrontierLap,
{
    let mut clean: Vec<&L> = rows.iter().filter(|row| !row.dirty()).collect();
    clean.sort_by_key(|row| row.best_lap_ms());
    let mut seen: HashSet<(String, String, String, String)> = HashSet::new();
    let mut out = Vec::new();
    for row in clean {
        let key = (
            row.track().to_string(),
            row.race_class().to_string(),
            row.driver().to_string(),
            row.car().to_string(),
        );
        if seen.insert(key) {
            out.push(row);
        }
    }
    out
}

fn condition_key(row: &impl FrontierLap) -> String {
    row.weather().unwrap_or("unknown").to_string()
}

fn temp_key(row: &impl FrontierLap) -> Option<f64> {
    row.temp_f().map(|t| (t * 10.0).round() / 10.0)
}

/// Player-side frontier per (track, class, car, condition) with dominance by
/// time then temperature, plus opponents faster than the player's overall
/// limit, deduplicated per opponent identity.
///
/// Mirrors `FrontierCalculator.clean_frontier_rows`.
type PlayerGroups = HashMap<(String, String, String, String), Vec<(i64, Option<f64>, usize)>>;
type OverallGroups = HashMap<(String, String, String), Vec<(i64, Option<f64>, usize)>>;

pub fn clean_frontier_rows<L>(rows: &[L], gamertag: &str) -> Vec<FrontierWinner>
where
    L: FrontierLap,
{
    if rows.is_empty() {
        return Vec::new();
    }
    let name_lower = gamertag.to_lowercase();

    // player laps grouped by car-condition and overall-condition.
    let mut player_by_car: PlayerGroups = HashMap::new();
    let mut player_overall: OverallGroups = HashMap::new();

    for (idx, row) in rows.iter().enumerate() {
        if row.driver().to_lowercase() != name_lower {
            continue;
        }
        let condition = condition_key(row);
        let temp = temp_key(row);
        player_by_car
            .entry((
                row.track().to_string(),
                row.race_class().to_string(),
                row.car().to_string(),
                condition.clone(),
            ))
            .or_default()
            .push((row.best_lap_ms(), temp, idx));
        player_overall
            .entry((
                row.track().to_string(),
                row.race_class().to_string(),
                condition,
            ))
            .or_default()
            .push((row.best_lap_ms(), temp, idx));
    }

    let best_player_time = |candidates: &[(i64, Option<f64>, usize)]| -> Option<i64> {
        candidates.iter().map(|(time, _, _)| *time).min()
    };

    let dominates_time = |challenger_time: i64,
                          challenger_temp: Option<f64>,
                          current_time: i64,
                          current_temp: Option<f64>| {
        if challenger_time == current_time && challenger_temp == current_temp {
            return false;
        }
        if challenger_time > current_time {
            return false;
        }
        match (challenger_temp, current_temp) {
            (None, _) | (_, None) => challenger_temp == current_temp,
            (ct, cur) => ct <= cur,
        }
    };

    let is_frontier_record = |candidates: &[(i64, Option<f64>, usize)],
                              rows: &[L],
                              current_idx: usize,
                              current_time: i64,
                              current_temp: Option<f64>| {
        for (other_time, other_temp, other_idx) in candidates {
            if rows[*other_idx].image_file_id() == rows[current_idx].image_file_id() {
                continue;
            }
            if dominates_time(*other_time, *other_temp, current_time, current_temp) {
                return false;
            }
        }
        true
    };

    let mut kept: Vec<usize> = Vec::new();
    for (idx, row) in rows.iter().enumerate() {
        let condition = condition_key(row);
        let temp = temp_key(row);
        let overall = player_overall
            .get(&(
                row.track().to_string(),
                row.race_class().to_string(),
                condition.clone(),
            ))
            .map(Vec::as_slice)
            .unwrap_or(&[]);
        let Some(limit) = best_player_time(overall) else {
            continue;
        };

        if row.driver().to_lowercase() == name_lower {
            let candidates = player_by_car
                .get(&(
                    row.track().to_string(),
                    row.race_class().to_string(),
                    row.car().to_string(),
                    condition,
                ))
                .map(Vec::as_slice)
                .unwrap_or(&[]);
            if is_frontier_record(candidates, rows, idx, row.best_lap_ms(), temp) {
                kept.push(idx);
            }
        } else if row.best_lap_ms() < limit {
            kept.push(idx);
        }
    }

    // Opponent best per identity key.
    let mut opponent_best: HashMap<(String, String, String, String, String), i64> = HashMap::new();
    for &idx in &kept {
        let row = &rows[idx];
        if row.driver().to_lowercase() == name_lower {
            continue;
        }
        let key = (
            row.driver().to_string(),
            row.car().to_string(),
            row.track().to_string(),
            row.race_class().to_string(),
            condition_key(row),
        );
        let entry = opponent_best.entry(key).or_insert(row.best_lap_ms());
        if row.best_lap_ms() < *entry {
            *entry = row.best_lap_ms();
        }
    }

    // Claim one row per opponent identity.
    let mut claimed: HashSet<(String, String, String, String, String)> = HashSet::new();
    let mut final_rows: Vec<FrontierWinner> = Vec::new();
    for &idx in &kept {
        let row = &rows[idx];
        if row.driver().to_lowercase() == name_lower {
            final_rows.push(FrontierWinner {
                id: row.id().to_string(),
                image_file_id: row.image_file_id().to_string(),
            });
            continue;
        }
        let key = (
            row.driver().to_string(),
            row.car().to_string(),
            row.track().to_string(),
            row.race_class().to_string(),
            condition_key(row),
        );
        if let Some(best) = opponent_best.get(&key)
            && row.best_lap_ms() == *best
            && claimed.insert(key)
        {
            final_rows.push(FrontierWinner {
                id: row.id().to_string(),
                image_file_id: row.image_file_id().to_string(),
            });
        }
    }

    final_rows.sort_by(|a, b| a.id.cmp(&b.id));
    final_rows
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Debug, Clone)]
    struct Row {
        id: String,
        image: String,
        track: &'static str,
        class: &'static str,
        weather: Option<&'static str>,
        temp: Option<f64>,
        driver: &'static str,
        car: &'static str,
        ms: i64,
        dirty: bool,
    }

    impl FrontierLap for Row {
        fn id(&self) -> &str {
            &self.id
        }
        fn image_file_id(&self) -> &str {
            &self.image
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
            self.temp
        }
        fn driver(&self) -> &str {
            self.driver
        }
        fn car(&self) -> &str {
            self.car
        }
        fn best_lap_ms(&self) -> i64 {
            self.ms
        }
        fn dirty(&self) -> bool {
            self.dirty
        }
    }

    fn rows() -> Vec<Row> {
        vec![
            Row {
                id: "p1".into(),
                image: "img1".into(),
                track: "Fuji",
                class: "A",
                weather: Some("dry"),
                temp: Some(80.0),
                driver: "Player",
                car: "CarX",
                ms: 90_000,
                dirty: false,
            },
            Row {
                id: "r1".into(),
                image: "img2".into(),
                track: "Fuji",
                class: "A",
                weather: Some("dry"),
                temp: Some(80.0),
                driver: "Rival",
                car: "CarY",
                ms: 89_000,
                dirty: false,
            },
            Row {
                id: "r2".into(),
                image: "img3".into(),
                track: "Fuji",
                class: "A",
                weather: Some("dry"),
                temp: Some(85.0),
                driver: "Rival",
                car: "CarY",
                ms: 89_500,
                dirty: false,
            },
            Row {
                id: "d1".into(),
                image: "img4".into(),
                track: "Fuji",
                class: "A",
                weather: Some("dry"),
                temp: Some(80.0),
                driver: "Player",
                car: "CarX",
                ms: 88_000,
                dirty: true,
            },
        ]
    }

    #[test]
    fn simple_best_dedup_per_identity_and_skips_dirty() {
        let r = rows();
        let best = simple_best_rows(&r);
        let ids: Vec<&str> = best.iter().map(|x| x.id.as_str()).collect();
        // Clean-only path: dirty d1 excluded; rivals dedup to their fastest.
        assert_eq!(ids.len(), 2, "{ids:?}");
        assert!(ids.contains(&"p1"));
        assert!(ids.contains(&"r1"));
    }

    #[test]
    fn player_dirty_lap_sets_the_limit_and_wins_the_frontier() {
        // Mirrors Python: clean_frontier_rows does NOT filter dirty rows on
        // the player side. The dirty 88s sets the overall limit (dropping the
        // slower clean 90s record and both rivals) and wins the frontier —
        // which is exactly why dirty_lap review cases matter for output.
        let r = rows();
        let winners = clean_frontier_rows(&r, "player");
        let ids: Vec<&str> = winners.iter().map(|w| w.id.as_str()).collect();
        assert_eq!(ids, vec!["d1"], "{ids:?}");

        // Without the dirty row the clean record stands and the faster rival
        // is kept once at its best time.
        let clean_only: Vec<Row> = r.into_iter().filter(|row| row.id != "d1").collect();
        let winners = clean_frontier_rows(&clean_only, "player");
        let mut ids: Vec<&str> = winners.iter().map(|w| w.id.as_str()).collect();
        ids.sort_unstable();
        assert_eq!(ids, vec!["p1", "r1"], "{ids:?}");
    }

    #[test]
    fn empty_gamertag_yields_no_player_limit_so_only_new_unique_survive_simple_path() {
        let r = vec![Row {
            id: "a".into(),
            image: "i".into(),
            track: "T",
            class: "A",
            weather: None,
            temp: None,
            driver: "x",
            car: "c",
            ms: 1000,
            dirty: false,
        }];
        assert!(clean_frontier_rows(&r, "").is_empty());
    }
}
