//! Canonical request evidence hashing. Ported from `forza/db/evidence.py`:
//! the hash covers the exact redacted request payload persisted in SQLite.

use sha2::{Digest, Sha256};

/// Python-compatible canonical JSON:
/// `json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))`.
///
/// serde_json's default object map is a `BTreeMap`, so nested keys serialize
/// in sorted order exactly like `sort_keys=True`.
pub fn python_json_dumps(value: &serde_json::Value) -> String {
    match value {
        serde_json::Value::Null => "null".to_string(),
        serde_json::Value::Bool(b) => b.to_string(),
        serde_json::Value::Number(n) => n.to_string(),
        serde_json::Value::String(s) => python_json_string(s),
        serde_json::Value::Array(items) => {
            let parts: Vec<String> = items.iter().map(python_json_dumps).collect();
            format!("[{}]", parts.join(","))
        }
        serde_json::Value::Object(map) => {
            let parts: Vec<String> = map
                .iter()
                .map(|(k, v)| format!("{}:{}", python_json_string(k), python_json_dumps(v)))
                .collect();
            format!("{{{}}}", parts.join(","))
        }
    }
}

/// `json.dumps` string escaping with `ensure_ascii=True`: everything above
/// `~` becomes `\uXXXX` (surrogate pairs for astral code points).
fn python_json_string(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    out.push('"');
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => {
                out.push_str(&format!("\\u{:04x}", c as u32));
            }
            c if (c as u32) <= 0x7e => out.push(c),
            c => {
                let code = c as u32;
                if code <= 0xFFFF {
                    out.push_str(&format!("\\u{code:04x}"));
                } else {
                    let v = code - 0x1_0000;
                    let hi = 0xD800 + (v >> 10);
                    let lo = 0xDC00 + (v & 0x3FF);
                    out.push_str(&format!("\\u{hi:04x}\\u{lo:04x}"));
                }
            }
        }
    }
    out.push('"');
    out
}

fn opt_json_string(value: Option<&str>) -> String {
    match value {
        Some(s) => python_json_string(s),
        None => "null".to_string(),
    }
}

fn json_column(value: Option<&str>) -> String {
    match value {
        // JSON columns are re-canonicalized like the Python read model
        // (SQLModel parses the stored text, dumps re-sorts keys).
        Some(text) => match serde_json::from_str::<serde_json::Value>(text) {
            Ok(parsed) => python_json_dumps(&parsed),
            Err(_) => python_json_string(text),
        },
        None => "null".to_string(),
    }
}

/// Hash the exact redacted request evidence persisted in SQLite
/// (mirrors `forza.db.evidence.canonical_request_hash`).
#[allow(clippy::too_many_arguments)]
pub fn canonical_request_hash(
    request_messages_json: Option<&str>,
    request_config_json: Option<&str>,
    prompt_snapshot_id: Option<&str>,
    model: Option<&str>,
    source_file_hash: Option<&str>,
    request_image_format: Option<&str>,
    request_image_mime_type: Option<&str>,
    request_image_width: Option<i64>,
    request_image_height: Option<i64>,
    request_image_bytes: Option<i64>,
) -> String {
    let opt_str = |v: Option<&str>| opt_json_string(v);
    let opt_int = |v: Option<i64>| match v {
        Some(n) => n.to_string(),
        None => "null".to_string(),
    };
    let canonical = format!(
        "{{\"model\":{},\"prompt_snapshot_id\":{},\"request_config_json\":{},\
         \"request_image_bytes\":{},\"request_image_format\":{},\
         \"request_image_height\":{},\"request_image_mime_type\":{},\
         \"request_image_width\":{},\"request_messages_json\":{},\
         \"source_file_hash\":{}}}",
        opt_str(model),
        opt_str(prompt_snapshot_id),
        json_column(request_config_json),
        opt_int(request_image_bytes),
        opt_str(request_image_format),
        opt_int(request_image_height),
        opt_str(request_image_mime_type),
        opt_int(request_image_width),
        json_column(request_messages_json),
        opt_str(source_file_hash),
    );
    let digest = Sha256::digest(canonical.as_bytes());
    format!("{digest:x}")
}

#[cfg(test)]
mod tests {
    use super::canonical_request_hash;

    // Golden value generated with Python:
    // json.dumps(canonical, ensure_ascii=True, sort_keys=True,
    //            separators=(",", ":")) + sha256.
    #[test]
    fn request_hash_matches_python_golden() {
        let got = canonical_request_hash(
            Some(r#"[{"content":"hello","role":"user"}]"#),
            Some(r#"{"model":"qwen","temperature":0.7}"#),
            Some("p:abc"),
            Some("qwen2-7b"),
            Some("deadbeef_123"),
            Some("png"),
            Some("image/png"),
            Some(1600),
            Some(900),
            Some(2048),
        );
        assert_eq!(
            got,
            "c32760b55db2e032aea8f379825a129a4f55d145e38771ff3985a87dae83b363"
        );
    }
}
