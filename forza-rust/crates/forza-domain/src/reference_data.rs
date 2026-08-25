//! Embedded reference catalog loaded from versioned assets at compile time.

use crate::normalizer::ReferenceData;
use crate::text_utils;

/// Canonical track names (one per line).
pub const TRACKS_TXT: &str = include_str!("../../../assets/tracks.txt");
/// Canonical car names (one per line).
pub const CARS_TXT: &str = include_str!("../../../assets/cars.txt");

/// Reference data built from the embedded assets.
pub fn embedded_reference_data() -> ReferenceData {
    ReferenceData::from_lines(
        text_utils::load_nonempty_lines_from_str(TRACKS_TXT),
        text_utils::load_nonempty_lines_from_str(CARS_TXT),
    )
}
