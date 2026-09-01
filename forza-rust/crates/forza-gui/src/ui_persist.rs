//! Persist window geometry and splitter/column sizes across restarts.
//! Stored as JSON next to the INI config (`ui_state.json`), not inside the INI,
//! to keep `forza_config.ini` human-editable and avoid merge conflicts.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct WindowState {
    pub width: Option<f32>,
    pub height: Option<f32>,
    pub x: Option<i32>,
    pub y: Option<i32>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SplitState {
    pub images_table_split: Option<f32>,
    pub images_preview_h: Option<f32>,
    pub review_main_split: Option<f32>,
    pub review_preview_h: Option<f32>,
    pub detail_preview_split: Option<f32>,
    pub debug_table_h: Option<f32>,
    pub process_progress_h: Option<f32>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct UiPersist {
    pub window: WindowState,
    pub splits: SplitState,
    /// Column widths keyed as "page.col" -> px (e.g. "images.col-name-w")
    #[serde(default)]
    pub columns: HashMap<String, f32>,
}

fn state_path(config_path: &Path) -> PathBuf {
    if let Some(dir) = config_path.parent() {
        dir.join("ui_state.json")
    } else {
        PathBuf::from("ui_state.json")
    }
}

pub fn load(config_path: &Path) -> Option<UiPersist> {
    let path = state_path(config_path);
    let text = std::fs::read_to_string(&path).ok()?;
    serde_json::from_str(&text).ok()
}

pub fn save(config_path: &Path, state: &UiPersist) -> anyhow::Result<()> {
    let path = state_path(config_path);
    if let Some(dir) = path.parent() {
        if !dir.as_os_str().is_empty() {
            std::fs::create_dir_all(dir)?;
        }
    }
    let text = serde_json::to_string_pretty(state)?;
    // Atomic write via tmp + rename
    let tmp = path.with_extension("json.tmp");
    std::fs::write(&tmp, text)?;
    std::fs::rename(&tmp, &path)?;
    Ok(())
}
