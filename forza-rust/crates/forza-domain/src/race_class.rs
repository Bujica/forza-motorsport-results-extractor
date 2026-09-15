//! Class identity, ordering, and presentation colors.
//!
//! Single source of truth for race classes: [`crate::enums::RaceClass`] owns
//! the persisted value (`as_str`/`from_value`) while this module owns the
//! derived properties (sort order, GUI/PDF color, spec-vs-letter grouping).
//! Callers must go through [`crate::enums::RaceClass`] instead of matching
//! on raw strings so a new class becomes a compile error, not a silent
//! fallback color.

use crate::enums::RaceClass;

impl AsRef<str> for RaceClass {
    fn as_ref(&self) -> &str {
        self.as_str()
    }
}

impl RaceClass {
    /// Canonical class ordering used by reports, GUI, and frontier sorting.
    ///
    /// Appended spec divisions sort after the fallback buckets; Python-parity
    /// values (`E`=1..`Unknown`=12) must not move.
    #[must_use]
    pub const fn order(self) -> u32 {
        match self {
            Self::E => 1,
            Self::D => 2,
            Self::C => 3,
            Self::B => 4,
            Self::A => 5,
            Self::Tcr => 6,
            Self::S => 7,
            Self::R => 8,
            Self::P => 9,
            Self::X => 10,
            Self::Mixed => 11,
            Self::Unknown => 12,
            // Appended after the Python-parity values (which must not move):
            // spec divisions sort after the fallback buckets.
            Self::Gt2 => 13,
            Self::Gt3 => 14,
        }
    }

    /// Presentation color per class, matching the Python PDF/GUI contract.
    #[must_use]
    pub const fn color(self) -> &'static str {
        match self {
            Self::E => "#C7368E",
            Self::D => "#127F85",
            Self::C => "#BB7A00",
            Self::B => "#C54E00",
            Self::A => "#992800",
            Self::Tcr => "#1E90FF",
            Self::S => "#613BBF",
            Self::R => "#105DAB",
            Self::P => "#0C8540",
            Self::X => "#006000",
            Self::Mixed => "#555555",
            Self::Unknown => "#000000",
            Self::Gt2 => "#DAA520",
            Self::Gt3 => "#FF6347",
        }
    }

    /// Spec/division classes decided by car roster (`TCR`/`GT2`/`GT3`).
    #[must_use]
    pub const fn is_spec(self) -> bool {
        matches!(self, Self::Tcr | Self::Gt2 | Self::Gt3)
    }

    /// Single-letter performance classes (`E`..`X`).
    #[must_use]
    pub const fn is_letter(self) -> bool {
        matches!(
            self,
            Self::E | Self::D | Self::C | Self::B | Self::A | Self::S | Self::R | Self::P | Self::X
        )
    }

    /// Parse a free-form cell (CSV `Class`, LLM text) with the same rules as
    /// the import path: trim, uppercase, `TCR`/`GT2`/`GT3` prefix wins, else
    /// first character, else `Unknown`.
    ///
    /// # Examples
    ///
    /// ```
    /// use forza_domain::enums::RaceClass;
    ///
    /// assert_eq!(RaceClass::from_csv_cell("gt3 field"), RaceClass::Gt3);
    /// assert_eq!(RaceClass::from_csv_cell("  A  "), RaceClass::A);
    /// assert_eq!(RaceClass::from_csv_cell(""), RaceClass::Unknown);
    /// ```
    #[must_use]
    pub fn from_csv_cell(value: &str) -> Self {
        let v = value.trim().to_uppercase();
        if v.is_empty() {
            return Self::Unknown;
        }
        if v.starts_with("TCR") {
            return Self::Tcr;
        }
        if v.starts_with("GT2") {
            return Self::Gt2;
        }
        if v.starts_with("GT3") {
            return Self::Gt3;
        }
        match v.chars().next() {
            Some(c) => Self::from_value(&c.to_string()).unwrap_or(Self::Unknown),
            None => Self::Unknown,
        }
    }
}

/// Canonical class ordering used by reports, GUI, and frontier sorting.
///
/// Compatibility shim over [`RaceClass::order`]: unknown strings keep the
/// historical `99` fallback so SQL-adjacent callers don't conflate garbage
/// with `Unknown` (12).
pub fn class_order(race_class: &str) -> u32 {
    race_class
        .parse::<RaceClass>()
        .map(|c| c.order())
        .unwrap_or(99)
}

/// Presentation color per class, matching the Python PDF/GUI contract.
///
/// Compatibility shim over [`RaceClass::color`]: unknown strings keep the
/// historical `#000000` fallback.
/// Plain `match` (was a `LazyLock<HashMap>`): 14 fixed entries need no hash.
pub fn class_color(race_class: &str) -> &'static str {
    race_class
        .parse::<RaceClass>()
        .map(|c| c.color())
        .unwrap_or("#000000")
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

    #[test]
    fn every_variant_has_order_and_non_fallback_color() {
        // Exhaustive: adding a variant forces its order/color here instead of
        // silently falling back to 99/black in Best Laps output.
        for class in RaceClass::ALL {
            let _ = match *class {
                RaceClass::E
                | RaceClass::D
                | RaceClass::C
                | RaceClass::B
                | RaceClass::A
                | RaceClass::Tcr
                | RaceClass::Gt2
                | RaceClass::Gt3
                | RaceClass::S
                | RaceClass::R
                | RaceClass::P
                | RaceClass::X
                | RaceClass::Mixed
                | RaceClass::Unknown => class.order(),
            };
            let _ = match *class {
                RaceClass::E
                | RaceClass::D
                | RaceClass::C
                | RaceClass::B
                | RaceClass::A
                | RaceClass::Tcr
                | RaceClass::Gt2
                | RaceClass::Gt3
                | RaceClass::S
                | RaceClass::R
                | RaceClass::P
                | RaceClass::X
                | RaceClass::Mixed
                | RaceClass::Unknown => class.color(),
            };
            if *class != RaceClass::Unknown {
                assert_ne!(
                    class.color(),
                    "#000000",
                    "missing color for {}",
                    class.as_str()
                );
            }
            assert_eq!(class.as_str().parse::<RaceClass>(), Ok(*class));
        }
    }

    #[test]
    fn csv_cell_parsing_matches_import_rules() {
        assert_eq!(RaceClass::from_csv_cell(" tcr "), RaceClass::Tcr);
        assert_eq!(RaceClass::from_csv_cell("TCR something"), RaceClass::Tcr);
        assert_eq!(RaceClass::from_csv_cell("gt3 field"), RaceClass::Gt3);
        assert_eq!(RaceClass::from_csv_cell("GT2"), RaceClass::Gt2);
        assert_eq!(RaceClass::from_csv_cell("A"), RaceClass::A);
        assert_eq!(RaceClass::from_csv_cell(""), RaceClass::Unknown);
    }
}
