//! Domain error types.

use std::fmt;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DomainError {
    /// Lap time milliseconds must be strictly positive.
    NonPositiveLapTime,
    /// A textual enum value does not match the persisted vocabulary.
    UnknownEnumValue {
        enum_name: &'static str,
        value: String,
    },
}

impl fmt::Display for DomainError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            DomainError::NonPositiveLapTime => {
                write!(f, "lap time milliseconds must be positive")
            }
            DomainError::UnknownEnumValue { enum_name, value } => {
                write!(f, "unknown {enum_name} value: {value}")
            }
        }
    }
}

impl std::error::Error for DomainError {}
