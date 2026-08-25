//! Persisted and GUI-facing enums with explicit textual representation.
//!
//! Every variant carries an explicit `&'static str` value. Variant declaration
//! order is never relied upon for persistence or display.

/// Generate a domain enum with explicit persisted string values.
macro_rules! value_enum {
    (
        $(#[$meta:meta])*
        pub enum $name:ident {
            $($variant:ident = $value:expr),+ $(,)?
        }
    ) => {
        $(#[$meta])*
        #[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
        pub enum $name {
            $($variant),+
        }

        impl $name {
            /// Explicit persisted/display value.
            pub const ALL: &'static [$name] = &[$($name::$variant),+];

            pub const fn as_str(self) -> &'static str {
                match self {
                    $($name::$variant => $value),+
                }
            }

            /// All persisted values in declaration order.
            pub const VALUES: &'static [&'static str] = &[$($value),+];

            pub fn from_value(value: &str) -> Option<Self> {
                match value {
                    $($value => Some($name::$variant),)+
                    _ => None,
                }
            }
        }

        impl std::fmt::Display for $name {
            fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                f.write_str(self.as_str())
            }
        }

        impl std::str::FromStr for $name {
            type Err = $crate::errors::DomainError;

            fn from_str(s: &str) -> Result<Self, Self::Err> {
                Self::from_value(s).ok_or_else(|| {
                    $crate::errors::DomainError::UnknownEnumValue {
                        enum_name: stringify!($name),
                        value: s.to_string(),
                    }
                })
            }
        }
    };
}

value_enum! {
    /// Weather vocabulary used across persistence, reports, and GUI.
    pub enum WeatherType {
        Dry = "dry",
        Rain = "rain",
        Unknown = "unknown",
    }
}

value_enum! {
    /// Status of a single image extraction result.
    pub enum ExtractionStatus {
        Ok = "ok",
        Error = "error",
        Cancelled = "cancelled",
    }
}

value_enum! {
    /// Status of a single model attempt.
    pub enum AttemptStatus {
        Ok = "ok",
        Error = "error",
        Cancelled = "cancelled",
    }
}

value_enum! {
    /// Lifecycle status of a complete extraction run.
    pub enum RunStatus {
        Pending = "pending",
        Running = "running",
        Completed = "completed",
        Failed = "failed",
        Cancelled = "cancelled",
    }
}

value_enum! {
    pub enum RunMode {
        Normal = "normal",
        DryRun = "dry_run",
    }
}

value_enum! {
    pub enum ImageFileStatus {
        Available = "available",
        Missing = "missing",
    }
}

value_enum! {
    pub enum BestLapStatus {
        Pending = "pending",
        Contributing = "contributing",
        NonContributing = "non_contributing",
    }
}

value_enum! {
    /// Derived processing status shown by the Images inventory.
    pub enum ImageProcessingStatus {
        Unprocessed = "unprocessed",
        Processing = "processing",
        ProcessedOk = "processed_ok",
        ProcessedError = "processed_error",
        Cancelled = "cancelled",
        Skipped = "skipped",
    }
}

value_enum! {
    pub enum ImageFlagStatus {
        Active = "active",
        Resolved = "resolved",
        Ignored = "ignored",
    }
}

value_enum! {
    pub enum ImageFlagType {
        Duplicate = "duplicate",
        DirtyLap = "dirty_lap",
        Track = "track",
        Weather = "weather",
        RaceClass = "race_class",
        Car = "car",
        DriverName = "driver_name",
    }
}

value_enum! {
    pub enum ReviewCaseStatus {
        Open = "open",
        Resolved = "resolved",
        Ignored = "ignored",
        AutoResolved = "auto_resolved",
    }
}

value_enum! {
    pub enum ReviewOutcome {
        Pending = "pending",
        Confirmed = "confirmed",
        ModelError = "model_error",
        Ignored = "ignored",
    }
}

value_enum! {
    pub enum ReviewReason {
        DirtyLap = "dirty_lap",
        Track = "track",
        Weather = "weather",
        RaceClass = "race_class",
        Car = "car",
        DriverName = "driver_name",
    }
}

value_enum! {
    pub enum ReviewTrigger {
        ModelMarkedDirty = "model_marked_dirty",
        WeatherUnknown = "weather_unknown",
        RainTimeSuspicious = "rain_time_suspicious",
        TrackUnknown = "track_unknown",
        TrackUnresolved = "track_unresolved",
        TrackNotInReference = "track_not_in_reference",
        ClassUnknown = "class_unknown",
        ClassInvalid = "class_invalid",
        CarEmpty = "car_empty",
        CarNotInReference = "car_not_in_reference",
        DriverNameEmpty = "driver_name_empty",
        NumericPrefix = "numeric_prefix",
        InvalidSymbol = "invalid_symbol",
    }
}

value_enum! {
    pub enum ReviewDecisionField {
        Dirty = "dirty",
        Track = "track",
        Weather = "weather",
        RaceClass = "race_class",
        Car = "car",
        Driver = "driver",
    }
}

value_enum! {
    pub enum CorrectionCause {
        Review = "review",
        Rebuild = "rebuild",
        Auto = "auto",
        Unknown = "unknown",
    }
}

value_enum! {
    pub enum RuntimeSnapshotKind {
        Preflight = "preflight",
    }
}

value_enum! {
    pub enum ExportFormat {
        Csv = "csv",
        Pdf = "pdf",
    }
}

value_enum! {
    /// Race class letters plus the composite TCR/Mixed/Unknown values.
    pub enum RaceClass {
        E = "E",
        D = "D",
        C = "C",
        B = "B",
        A = "A",
        Tcr = "TCR",
        S = "S",
        R = "R",
        P = "P",
        X = "X",
        Mixed = "Mixed",
        Unknown = "Unknown",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn persisted_values_match_python_contract() {
        assert_eq!(WeatherType::VALUES, ["dry", "rain", "unknown"]);
        assert_eq!(
            RunStatus::VALUES,
            ["pending", "running", "completed", "failed", "cancelled"]
        );
        assert_eq!(RunMode::VALUES, ["normal", "dry_run"]);
        assert_eq!(
            BestLapStatus::VALUES,
            ["pending", "contributing", "non_contributing"]
        );
        assert_eq!(
            ReviewCaseStatus::VALUES,
            ["open", "resolved", "ignored", "auto_resolved"]
        );
        assert_eq!(
            ReviewOutcome::VALUES,
            ["pending", "confirmed", "model_error", "ignored"]
        );
        assert_eq!(
            ReviewTrigger::VALUES,
            [
                "model_marked_dirty",
                "weather_unknown",
                "rain_time_suspicious",
                "track_unknown",
                "track_unresolved",
                "track_not_in_reference",
                "class_unknown",
                "class_invalid",
                "car_empty",
                "car_not_in_reference",
                "driver_name_empty",
                "numeric_prefix",
                "invalid_symbol"
            ]
        );
        assert_eq!(
            ReviewDecisionField::VALUES,
            ["dirty", "track", "weather", "race_class", "car", "driver"]
        );
        assert_eq!(
            CorrectionCause::VALUES,
            ["review", "rebuild", "auto", "unknown"]
        );
        assert_eq!(RaceClass::from_value("TCR"), Some(RaceClass::Tcr));
        assert_eq!(RaceClass::Tcr.as_str(), "TCR");
        assert_eq!("Mixed".parse::<RaceClass>().unwrap(), RaceClass::Mixed);
    }
}
