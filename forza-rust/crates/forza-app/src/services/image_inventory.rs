//! Application-facing image inventory service.

use std::path::{Path, PathBuf};

use forza_db::gui_queries as db;

/// One row of the Images list as consumed by the GUI.
#[derive(Debug, Clone, PartialEq)]
pub struct ImageInventoryEntry {
    pub id: String,
    pub name: String,
    pub file_status: String,
    pub best_lap_status: String,
    pub processing_status: String,
    pub size_bytes: Option<i64>,
}

#[derive(Debug, Clone, PartialEq, Default)]
pub struct ImageInventoryOptions {
    pub tracks: Vec<String>,
    pub runs: Vec<String>,
}

#[derive(Debug, Clone, Default)]
pub struct ImageInventoryFilter {
    pub file_status: Option<String>,
    pub processing_status: Option<String>,
    pub run_id: Option<String>,
    pub best_lap_status: Option<String>,
    pub inventory_filter: Option<String>,
    pub track: Option<String>,
    pub include_missing_files: bool,
}

impl ImageInventoryFilter {
    fn to_db(&self) -> db::ImageInventoryFilter {
        db::ImageInventoryFilter {
            file_status: self.file_status.clone(),
            processing_status: self.processing_status.clone(),
            run_id: self.run_id.clone(),
            best_lap_status: self.best_lap_status.clone(),
            inventory_filter: self.inventory_filter.clone(),
            track: self.track.clone(),
            include_missing_files: self.include_missing_files,
        }
    }
}

fn to_entry(row: db::ImageInventoryRow) -> ImageInventoryEntry {
    ImageInventoryEntry {
        id: row.id,
        name: row.current_name,
        file_status: row.file_status,
        best_lap_status: row.best_lap_status,
        processing_status: row.processing_status,
        size_bytes: row.file_size_bytes,
    }
}

/// Reads the Images inventory through the read facade.
pub struct ImageInventoryService {
    database_file: PathBuf,
}

impl ImageInventoryService {
    pub fn new(database_file: impl Into<PathBuf>) -> Self {
        Self {
            database_file: database_file.into(),
        }
    }

    pub fn database_file(&self) -> &Path {
        &self.database_file
    }

    /// List the inventory applying the filter. Opens a short-lived
    /// configured connection per call (WAL keeps readers lock-free).
    pub fn list(
        &self,
        filter: &ImageInventoryFilter,
    ) -> Result<Vec<ImageInventoryEntry>, forza_db::DbError> {
        let conn = forza_db::open_connection(&self.database_file)?;
        Ok(db::image_inventory(&conn, &filter.to_db())?
            .into_iter()
            .map(to_entry)
            .collect())
    }

    pub fn options(&self) -> Result<ImageInventoryOptions, forza_db::DbError> {
        let conn = forza_db::open_connection(&self.database_file)?;
        let (tracks, runs) = db::image_inventory_options(&conn)?;
        Ok(ImageInventoryOptions { tracks, runs })
    }
}
