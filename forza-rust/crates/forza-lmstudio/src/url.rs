//! LM Studio endpoint URL normalization (single owner).
//!
//! Both the metadata client and the chat backend trim a configured URL down
//! to its API root; the two copies drifted before (`chat_url` vs `api_base`),
//! so all normalization lives here now.

/// Reduce a configured server URL to its `/api/v1` root.
///
/// - trailing slashes are ignored;
/// - an embedded `/api/v1/` or `/v1/` path is cut back to the API root;
/// - a bare host (with port/subpath) is returned as-is.
pub fn api_base(url: &str) -> String {
    let clean = url.trim_end_matches('/');
    if let Some(idx) = clean.find("/api/v1/") {
        return format!("{}/api/v1", &clean[..idx]);
    }
    if clean.ends_with("/api/v1") {
        return clean.to_string();
    }
    if let Some(idx) = clean.find("/v1/") {
        return format!("{}/api/v1", &clean[..idx]);
    }
    clean.to_string()
}

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use super::api_base;

    #[test]
    fn api_base_edge_cases() {
        assert_eq!(api_base("http://localhost:1234"), "http://localhost:1234");
        assert_eq!(api_base("http://localhost:1234/"), "http://localhost:1234");
        assert_eq!(
            api_base("http://localhost:1234/api/v1"),
            "http://localhost:1234/api/v1"
        );
        assert_eq!(
            api_base("http://localhost:1234/api/v1/"),
            "http://localhost:1234/api/v1"
        );
        assert_eq!(
            api_base("http://localhost:1234/api/v1/models"),
            "http://localhost:1234/api/v1"
        );
        assert_eq!(
            api_base("http://localhost:1234/v1/chat"),
            "http://localhost:1234/api/v1"
        );
        assert_eq!(
            api_base("http://host:8080/subpath"),
            "http://host:8080/subpath"
        );
    }
}
