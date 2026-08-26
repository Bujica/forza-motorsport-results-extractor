//! Thin binary wrapper around the GUI library entry point.

fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .init();
    let config = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "forza_config.ini".to_string());
    forza_gui::run(std::path::Path::new(&config))
}
