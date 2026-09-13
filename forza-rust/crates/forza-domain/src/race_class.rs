//! Class letter ordering and presentation colors.

/// Canonical class ordering used by reports, GUI, and frontier sorting.
pub fn class_order(race_class: &str) -> u32 {
    match race_class {
        "E" => 1,
        "D" => 2,
        "C" => 3,
        "B" => 4,
        "A" => 5,
        "TCR" => 6,
        "S" => 7,
        "R" => 8,
        "P" => 9,
        "X" => 10,
        "Mixed" => 11,
        "Unknown" => 12,
        // Appended after the Python-parity values (which must not move):
        // spec divisions sort after the fallback buckets.
        "GT2" => 13,
        "GT3" => 14,
        _ => 99,
    }
}

/// Presentation color per class, matching the Python PDF/GUI contract.
/// Plain `match` (was a `LazyLock<HashMap>`): 12 fixed entries need no hash.
pub fn class_color(race_class: &str) -> &'static str {
    match race_class {
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
        "GT2" => "#DAA520",
        "GT3" => "#FF6347",
        _ => "#000000",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn class_order_matches_python() {
        assert_eq!(class_order("E"), 1);
        assert_eq!(class_order("A"), 5);
        assert_eq!(class_order("TCR"), 6);
        assert_eq!(class_order("Mixed"), 11);
        assert_eq!(class_order("Unknown"), 12);
        assert_eq!(class_order("Whatever"), 99);
    }

    #[test]
    fn spec_divisions_sort_after_fallbacks() {
        // Appended past the Python-parity values, which must not move.
        assert_eq!(class_order("GT2"), 13);
        assert_eq!(class_order("GT3"), 14);
    }

    #[test]
    fn class_colors_complete() {
        for (class, color) in [
            ("E", "#C7368E"),
            ("D", "#127F85"),
            ("C", "#BB7A00"),
            ("B", "#C54E00"),
            ("A", "#992800"),
            ("TCR", "#1E90FF"),
            ("S", "#613BBF"),
            ("R", "#105DAB"),
            ("P", "#0C8540"),
            ("X", "#006000"),
            ("Mixed", "#555555"),
            ("Unknown", "#000000"),
            ("GT2", "#DAA520"),
            ("GT3", "#FF6347"),
        ] {
            assert_eq!(class_color(class), color, "wrong color for {class}");
        }
        assert_eq!(class_color("Whatever"), "#000000");
    }
}
