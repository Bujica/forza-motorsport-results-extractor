//! Doctor report types shared by all check modules.

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DoctorSeverity {
    Error,
    Warning,
    Info,
}

impl DoctorSeverity {
    pub fn as_str(self) -> &'static str {
        match self {
            DoctorSeverity::Error => "error",
            DoctorSeverity::Warning => "warning",
            DoctorSeverity::Info => "info",
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct DoctorCheck {
    pub key: &'static str,
    pub ok: bool,
    pub count: i64,
    pub detail: String,
    pub severity: DoctorSeverity,
}

impl DoctorCheck {
    pub(super) fn new(
        key: &'static str,
        severity: DoctorSeverity,
        detail: impl Into<String>,
        count: i64,
    ) -> Self {
        DoctorCheck {
            key,
            ok: count == 0,
            count,
            detail: detail.into(),
            severity,
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct DoctorReport {
    pub ok: bool,
    pub schema_status: String,
    pub user_version: i64,
    pub checks: Vec<DoctorCheck>,
}

impl DoctorReport {
    pub(super) fn finish(mut self) -> Self {
        self.ok = self.schema_status == "current"
            && self
                .checks
                .iter()
                .all(|c| c.severity != DoctorSeverity::Error || c.ok);
        self
    }
}
