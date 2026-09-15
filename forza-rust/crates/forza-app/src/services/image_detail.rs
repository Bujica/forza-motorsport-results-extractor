//! Image Detail read facade — assembles the operator detail surface
//! (metadata + laps + review cases + extraction summaries + attempts) for
//! one image. Raw response bodies stay out of this facade (Image Debug owns
//! them, per the GUI contract).

use rusqlite::Connection;

use forza_db::image_detail::{
    DetailAttemptRow, DetailLapRow, DetailResultRow, ImageDetailMeta, attempts_for_image,
    image_detail_meta, laps_for_image, results_for_image,
};

use super::review_queue::ReviewCaseEntry;

/// Everything the Image Detail page renders for one image.
#[derive(Debug, Clone, PartialEq)]
pub struct ImageDetailData {
    pub meta: ImageDetailMeta,
    pub laps: Vec<DetailLapRow>,
    pub reviews: Vec<ReviewCaseEntry>,
    pub results: Vec<DetailResultRow>,
    pub attempts: Vec<DetailAttemptRow>,
}

/// Load the full detail bundle for one image. `Ok(None)` when the id is
/// unknown (the GUI shows the "Image not found" failure path).
pub fn load_image_detail(
    conn: &Connection,
    image_file_id: &str,
) -> Result<Option<ImageDetailData>, String> {
    let Some(meta) = image_detail_meta(conn, image_file_id).map_err(|e| e.to_string())? else {
        return Ok(None);
    };
    let laps = laps_for_image(conn, image_file_id).map_err(|e| e.to_string())?;
    let reviews = super::review_queue::list_review_cases(
        conn,
        &super::review_queue::ReviewQueueFilter {
            bucket: "all".to_string(),
            image_file_id: Some(image_file_id.to_string()),
            ..Default::default()
        },
    )?;
    let results = results_for_image(conn, image_file_id).map_err(|e| e.to_string())?;
    let attempts = attempts_for_image(conn, image_file_id).map_err(|e| e.to_string())?;
    Ok(Some(ImageDetailData {
        meta,
        laps,
        reviews,
        results,
        attempts,
    }))
}
