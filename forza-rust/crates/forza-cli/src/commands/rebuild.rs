//! `rebuild` command (derived state without model calls).

use std::path::Path;

use super::common::load_validated_config;

pub(crate) fn cmd_rebuild(config_path: &Path, strict: bool) -> anyhow::Result<()> {
    let cfg = load_validated_config(config_path, strict)?;
    let conn = forza_db::open_connection(&cfg.database_file)?;
    let outcome = forza_app::services::rebuild::rebuild(&conn, &cfg.gamertag)
        .map_err(|e| anyhow::anyhow!(e))?;
    println!(
        "rebuild: {} best-lap winner(s); reviews +{} kept {} auto-resolved {} (flags +{}/{})",
        outcome.best_lap_winners,
        outcome.review_inserted,
        outcome.review_kept,
        outcome.review_auto_resolved,
        outcome.flags_ensured,
        outcome.flags_resolved
    );
    Ok(())
}
