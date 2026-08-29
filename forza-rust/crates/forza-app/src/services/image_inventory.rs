//! Application-facing image inventory service.

use std::path::{Path, PathBuf};

use forza_db::gui_queries as db;
use rusqlite::params;

/// One row of the Images list as consumed by the GUI.
#[derive(Debug, Clone, PartialEq)]
pub struct ImageInventoryEntry {
    pub id: String,
    pub name: String,
    pub file_status: String,
    pub best_lap_status: String,
    pub processing_status: String,
    pub size_bytes: Option<i64>,
    pub race_date: Option<String>,
    pub semantic_name: Option<String>,
    pub file_hash: String,
    pub current_path: Option<String>,
    /// "Duplicate" / "Canonical" / "" display value.
    pub duplicate_label: String,
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
        duplicate_label: match row.duplicate_role {
            Some(false) => "Duplicate".to_string(),
            Some(true) => "Canonical".to_string(),
            None => String::new(),
        },
        id: row.id,
        name: row.current_name,
        file_status: row.file_status,
        best_lap_status: row.best_lap_status,
        processing_status: row.processing_status,
        size_bytes: row.file_size_bytes,
        race_date: row.race_date,
        semantic_name: row.semantic_name,
        file_hash: row.file_hash,
        current_path: row.current_path,
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

    /// Register supported files found in the configured input directory.
    ///
    /// This is the GUI equivalent of Python's `sync_input_folder`: it only
    /// updates the inventory and never contacts the model or creates a run.
    /// Returns the number of files newly registered.
    pub fn sync_input_folder(&self, input_dir: &Path) -> Result<usize, forza_db::DbError> {
        let images = forza_pipeline::find_images(input_dir);
        let conn = forza_db::open_connection(&self.database_file)?;
        let mut inserted = 0;

        for path in images {
            let Ok(file_hash) = forza_pipeline::file_hash(&path) else {
                continue;
            };
            let path_text = path.to_string_lossy().to_string();
            let name = path
                .file_name()
                .map(|value| value.to_string_lossy().to_string())
                .unwrap_or_default();
            let Some(metadata) = forza_pipeline::inspect_metadata(&path).ok() else {
                continue;
            };

            let existing_path: Option<String> = conn
                .query_row(
                    "SELECT id FROM image_files WHERE current_path = ?1 LIMIT 1",
                    [&path_text],
                    |row| row.get(0),
                )
                .optional()?;
            if let Some(id) = existing_path {
                conn.execute(
                    "UPDATE image_files
                     SET current_name=?2, file_hash=?3, file_status='available',
                         size_bytes=?4, width_px=?5, height_px=?6,
                         bit_depth=?7, color_mode=?8, image_metadata_json=?9,
                         file_modified_at=?10, race_datetime=?11, race_date=?12,
                         race_datetime_source=?13,
                         last_seen_at=datetime('now'), updated_at=datetime('now')
                     WHERE id=?1",
                    params![
                        id,
                        name,
                        file_hash,
                        metadata.file_size_bytes as i64,
                        metadata.width_px as i64,
                        metadata.height_px as i64,
                        metadata.bit_depth.map(|b| b as i64),
                        metadata.color_mode,
                        metadata.image_metadata_json,
                        metadata.file_modified_at,
                        metadata.race_datetime,
                        metadata.race_date,
                        metadata.race_datetime_source,
                    ],
                )?;
                continue;
            }

            let canonical_id: Option<String> = conn
                .query_row(
                    "SELECT id FROM image_files WHERE file_hash = ?1 ORDER BY created_at, id LIMIT 1",
                    [&file_hash],
                    |row| row.get(0),
                )
                .optional()?;
            let base_id = format!("img-{file_hash}");
            let mut id = base_id.clone();
            let mut suffix = 1;
            while conn
                .query_row(
                    "SELECT 1 FROM image_files WHERE id=?1 LIMIT 1",
                    [&id],
                    |_row| Ok(()),
                )
                .optional()?
                .is_some()
            {
                id = format!("{base_id}-{suffix}");
                suffix += 1;
            }
            let extension = metadata.image_format.to_lowercase();
            conn.execute(
                "INSERT INTO image_files
                 (id, file_hash, current_name, current_path, size_bytes,
                  width_px, height_px, image_format, mime_type,
                  bit_depth, color_mode, image_metadata_json,
                  file_modified_at, race_datetime, race_date, race_datetime_source,
                  file_status, best_lap_status, duplicate_of_image_file_id,
                  first_seen_at, last_seen_at, created_at, updated_at)
                 VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,
                         'available','pending',?17,
                         datetime('now'),datetime('now'),datetime('now'),datetime('now'))",
                params![
                    id,
                    file_hash,
                    name,
                    path_text,
                    metadata.file_size_bytes as i64,
                    metadata.width_px as i64,
                    metadata.height_px as i64,
                    extension,
                    metadata.mime_type,
                    metadata.bit_depth.map(|b| b as i64),
                    metadata.color_mode,
                    metadata.image_metadata_json,
                    metadata.file_modified_at,
                    metadata.race_datetime,
                    metadata.race_date,
                    metadata.race_datetime_source,
                    canonical_id,
                ],
            )?;
            inserted += 1;
        }
        Ok(inserted)
    }

    pub fn options(&self) -> Result<ImageInventoryOptions, forza_db::DbError> {
        let conn = forza_db::open_connection(&self.database_file)?;
        let (tracks, runs) = db::image_inventory_options(&conn)?;
        Ok(ImageInventoryOptions { tracks, runs })
    }
}

use rusqlite::OptionalExtension;
