// Unit-test modules exercise fallible helpers directly.
#![cfg_attr(test, allow(clippy::unwrap_used, clippy::expect_used))]

//! Pure domain rules and business types for Forza Motorsport Results Extractor.
//!
//! This crate has no filesystem, network, GUI, or database access. Reference
//! data is embedded at compile time from `assets/`.

// Textual scope: defined before the modules below, so every child module
// shares this one definition instead of repeating it (was copy-pasted in
// `lap`, `car_names`, `review_rules`).
/// Compile-once regex; patterns here are static and infallible.
macro_rules! lazy_regex {
    ($pattern:expr) => {
        ::std::sync::LazyLock::new(|| match ::regex::Regex::new($pattern) {
            Ok(re) => re,
            Err(err) => panic!("invalid built-in regex: {err}"),
        })
    };
}

pub mod car_names;
pub mod difflib;
pub mod enums;
pub mod errors;
pub mod frontier;
pub mod lap;
pub mod ordering;
pub mod race_class;
pub mod reference_data;
pub mod review_rules;
pub mod text_utils;

pub mod normalizer;
