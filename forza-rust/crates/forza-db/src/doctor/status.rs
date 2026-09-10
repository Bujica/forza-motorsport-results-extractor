//! Status vocabulary checks (status_checks.py).

use rusqlite::Connection;

use crate::error::DbError;

use super::helpers::check_sql;
use super::types::{DoctorCheck, DoctorSeverity};

// ── Status vocabulary (status_checks.py) ─────────────────────────────────────

const INVALID_STATUS_VALUES_SQL: &str = r#"
    SELECT
        (SELECT COUNT(*) FROM extraction_runs
         WHERE status NOT IN ('pending', 'running', 'completed', 'failed', 'cancelled'))
      + (SELECT COUNT(*) FROM extraction_results
         WHERE status NOT IN ('pending', 'running', 'ok', 'error', 'cancelled'))
      + (SELECT COUNT(*) FROM extraction_attempts
         WHERE status NOT IN ('ok', 'error', 'cancelled'))
      + (SELECT COUNT(*) FROM image_files
         WHERE file_status NOT IN ('available', 'missing')
            OR best_lap_status NOT IN ('pending', 'contributing', 'non_contributing'))
      + (SELECT COUNT(*) FROM review_cases
         WHERE status NOT IN ('open', 'resolved', 'ignored', 'auto_resolved')
            OR reason NOT IN ('dirty_lap', 'track', 'weather', 'race_class', 'car', 'driver_name')
            OR outcome NOT IN ('pending', 'confirmed', 'model_error', 'ignored')
            OR ("trigger" IS NOT NULL AND "trigger" NOT IN ('model_marked_dirty', 'weather_unknown', 'rain_time_suspicious', 'track_unknown', 'track_unresolved', 'track_not_in_reference', 'class_unknown', 'class_invalid', 'car_empty', 'car_not_in_reference', 'driver_name_empty', 'numeric_prefix', 'invalid_symbol'))
            OR (decision_field IS NOT NULL AND decision_field NOT IN ('dirty', 'track', 'weather', 'race_class', 'car', 'driver')))
      + (SELECT COUNT(*) FROM image_flags
         WHERE status NOT IN ('active', 'resolved', 'ignored')
            OR flag_scope NOT IN ('image', 'lap')
            OR flag_type NOT IN ('duplicate', 'dirty_lap', 'track', 'weather', 'race_class', 'car', 'driver_name'))
"#;

pub(super) fn invalid_status_values_check(conn: &Connection) -> Result<DoctorCheck, DbError> {
    check_sql(
        conn,
        "invalid_status_values",
        DoctorSeverity::Error,
        "Persisted lifecycle/status fields must use the DB vNext vocabulary.",
        INVALID_STATUS_VALUES_SQL,
    )
}
