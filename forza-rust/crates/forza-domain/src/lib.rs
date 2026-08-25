// Unit-test modules exercise fallible helpers directly.
#![cfg_attr(test, allow(clippy::unwrap_used, clippy::expect_used))]

//! Pure domain rules and business types for Forza Motorsport Results Extractor.
//!
//! This crate has no filesystem, network, GUI, or database access. Reference
//! data is embedded at compile time from `assets/`.

pub mod car_names;
pub mod difflib;
pub mod enums;
pub mod errors;
pub mod lap;
pub mod ordering;
pub mod race_class;
pub mod reference_data;
pub mod review_rules;
pub mod text_utils;

pub mod normalizer;
