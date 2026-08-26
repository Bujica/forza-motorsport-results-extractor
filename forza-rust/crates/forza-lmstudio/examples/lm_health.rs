//! Manual smoke against a running LM Studio instance:
//!   cargo run -p forza-lmstudio --example lm_health -- http://127.0.0.1:1234/api/v1/chat [model]

use forza_lmstudio::client::RuntimeClient;
use forza_lmstudio::load_config::{DesiredLoadConfig, NormalizedLoadConfig};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let url = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "http://127.0.0.1:1234/api/v1/chat".into());
    let model = std::env::args().nth(2).unwrap_or_default();

    let client = RuntimeClient::new(&url, 5);
    let health = client.health().await?;
    println!("health : {health}");

    let desired = DesiredLoadConfig {
        context_length: 5000,
        eval_batch_size: Some(1024),
        physical_batch_size: None,
        flash_attention: true,
        offload_kv_cache_to_gpu: true,
    };
    let diag = client.runtime_status(&model, &desired, Some("off")).await?;
    println!("level  : {}", diag.level);
    println!("message: {}", diag.message);
    for warning in &diag.warnings {
        println!("warn   : {warning}");
    }
    let _ = NormalizedLoadConfig::default();
    Ok(())
}
