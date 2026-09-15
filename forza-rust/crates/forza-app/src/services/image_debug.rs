//! Image Debug read facade — port of `GuiImageDebugReadQueries`.
//! Wraps the `forza-db` queries with the Python filtering contract
//! (post-fetch in-memory matching, limit, optional selected result).

use rusqlite::Connection;

use forza_db::image_debug::{
    ImageDebugCase, ImageDebugDetail, get_image_debug_detail, get_image_debug_detail_by_result,
    list_image_debug_cases,
};

#[derive(Debug, Clone, PartialEq, Default)]
pub struct ImageDebugFilter {
    pub status: Option<String>,
    pub backend: Option<String>,
    pub model: Option<String>,
    pub prompt_name: Option<String>,
    pub run_id: Option<String>,
}

fn matches(case: &ImageDebugCase, filter: &ImageDebugFilter) -> bool {
    let pairs: [(&Option<String>, &Option<String>); 5] = [
        (&filter.status, &case.latest_result_status),
        (&filter.backend, &case.backend),
        (&filter.model, &case.model),
        (&filter.prompt_name, &case.prompt_name),
        (&filter.run_id, &case.run_id),
    ];
    for (wanted, actual) in pairs {
        if let Some(value) = wanted
            && !value.is_empty()
            && value != "all"
            && Some(value) != actual.as_ref()
        {
            return false;
        }
    }
    true
}

/// List debug cases with optional filters (mirrors Python `list_image_debug_cases`).
pub fn list_debug_cases(
    conn: &Connection,
    filter: &ImageDebugFilter,
) -> Result<Vec<ImageDebugCase>, String> {
    let mut cases = list_image_debug_cases(conn, 500).map_err(|e| e.to_string())?;
    if filter.status.is_none()
        && filter.backend.is_none()
        && filter.model.is_none()
        && filter.prompt_name.is_none()
        && filter.run_id.is_none()
    {
        return Ok(cases);
    }
    cases.retain(|c| matches(c, filter));
    Ok(cases)
}

pub fn load_debug_detail(
    conn: &Connection,
    image_file_id: &str,
    selected_result_id: Option<&str>,
) -> Result<Option<ImageDebugDetail>, String> {
    get_image_debug_detail(conn, image_file_id, selected_result_id).map_err(|e| e.to_string())
}

pub fn load_debug_detail_by_result(
    conn: &Connection,
    extraction_result_id: &str,
) -> Result<Option<ImageDebugDetail>, String> {
    get_image_debug_detail_by_result(conn, extraction_result_id).map_err(|e| e.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn filter_matches_none_and_all_passthrough() {
        let mut f = ImageDebugFilter::default();
        let case = ImageDebugCase {
            image_file_id: "x".into(),
            image_name: "x".into(),
            race_date: None,
            file_status: "available".into(),
            processing_status: "processed_ok".into(),
            best_lap_status: "pending".into(),
            latest_result_id: Some("r".into()),
            latest_result_status: Some("ok".into()),
            run_id: Some("run1".into()),
            backend: Some("lmstudio".into()),
            model: Some("m".into()),
            prompt_name: Some("p".into()),
            attempt_count: 1,
            lap_count: 1,
            review_count: 0,
            artifact_count: 0,
            created_at: None,
        };
        assert!(matches(&case, &f));
        f.status = Some("all".into());
        assert!(matches(&case, &f));
        f.status = Some("ok".into());
        assert!(matches(&case, &f));
        f.status = Some("error".into());
        assert!(!matches(&case, &f));
    }
}
