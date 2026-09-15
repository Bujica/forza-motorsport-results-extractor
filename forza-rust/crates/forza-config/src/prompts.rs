//! Registered system prompts known to configuration validation.

/// Default prompt id used when `[prompt] active` is absent.
pub const DEFAULT_PROMPT_ID: &str = "user_header_shaped_v1";

/// All registered prompt ids. Full prompt texts live with the LM Studio
/// integration and snapshot logic (Fase 7).
pub const PROMPT_IDS: &[&str] = &[DEFAULT_PROMPT_ID];

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_prompt_is_registered() {
        assert!(PROMPT_IDS.contains(&DEFAULT_PROMPT_ID));
    }
}
