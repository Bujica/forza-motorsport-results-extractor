//! Minimal, deterministic JSON repair for model responses.
//!
//! Scope decision (recorded in the migration progress log): the real
//! malformed fixtures from this project fail on **validation**, not JSON
//! syntax — the Python `json_repair` pass re-serialized the same object.
//! This module therefore covers only the syntax-level repairs we have ever
//! observed: markdown fences (handled upstream), stray prose around the
//! object, trailing commas, smart quotes, and single-quoted strings.

/// Apply the deterministic repair pass to a raw response string.
pub fn repair_json(content: &str) -> String {
    let text = content.trim();
    // Window to outermost braces when prose surrounds the object.
    let windowed = match (text.find('{'), text.rfind('}')) {
        (Some(start), Some(end)) if end > start => &text[start..=end],
        _ => text,
    };

    let mut out = String::with_capacity(windowed.len());
    let mut in_string = false;
    let mut open_quote = '"';
    let mut escaped = false;
    let chars: Vec<char> = windowed.chars().collect();

    for i in 0..chars.len() {
        let ch = chars[i];
        if in_string {
            if escaped {
                out.push(ch);
                escaped = false;
            } else if ch == '\\' {
                out.push(ch);
                escaped = true;
            } else if ch == open_quote
                || (open_quote == '\u{201C}' && ch == '\u{201D}')
                || (open_quote == '\u{2018}' && ch == '\u{2019}')
            {
                // Replace the raw opening delimiter with a normalized quote.
                out.push('"');
                in_string = false;
            } else {
                out.push(ch);
            }
            continue;
        }
        match ch {
            '"' | '\'' | '\u{2018}' | '\u{201C}' | '\u{201D}' => {
                // Normalize every quote flavor to a plain double quote and
                // remember which one opened the string.
                open_quote = ch;
                in_string = true;
                out.push('"');
            }
            _ => {
                // Trailing comma before a closing bracket (outside strings).
                if ch == ',' {
                    let mut j = i + 1;
                    while j < chars.len() && chars[j].is_whitespace() {
                        j += 1;
                    }
                    if j < chars.len() && (chars[j] == '}' || chars[j] == ']') {
                        continue; // drop the trailing comma
                    }
                }
                out.push(ch);
            }
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn removes_trailing_commas_outside_strings() {
        assert_eq!(repair_json(r#"{"a":1,"b":2,}"#), r#"{"a":1,"b":2}"#);
        assert_eq!(
            repair_json("{\"e\":[{\"bl\":null},]}"),
            "{\"e\":[{\"bl\":null}]}"
        );
        assert_eq!(
            repair_json(r#"{"t":"has , comma"}"#),
            r#"{"t":"has , comma"}"#,
            "commas inside strings stay"
        );
    }

    #[test]
    fn converts_single_and_smart_quotes_outside_strings() {
        assert_eq!(repair_json("{'t':'x'}"), r#"{"t":"x"}"#);
        assert_eq!(repair_json("\u{201C}t\u{201D}:1 }"), "\"t\":1 }");
    }

    #[test]
    fn windows_prose_around_object() {
        assert_eq!(
            repair_json("Sure! {\"t\":\"x\"} hope it helps"),
            r#"{"t":"x"}"#
        );
    }

    #[test]
    fn preserves_string_content_verbatim() {
        let input = r#"{"t":"it's fine \"quoted\" , yes"}"#;
        assert_eq!(repair_json(input), input);
    }
}
