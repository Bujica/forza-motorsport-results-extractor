// Golden fixture harness: unwraps are idiomatic assertion helpers.
#![allow(clippy::unwrap_used, clippy::expect_used)]

//! Golden equivalence over the 50 real LM Studio responses extracted from
//! the 0.21.0-beta.1 baseline:
//!  - accepted responses must strict-parse AND match the stored parsed_json;
//!  - historically-malformed responses must also pass today's validation
//!    (their rejections came from older prompt/validation rules);
//!  - semantic retry issues must be empty for every accepted response.

use std::path::PathBuf;

use serde_json::Value;

use forza_lmstudio::response::{parse_and_validate_response, semantic_retry_issues};

fn fixture_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/model_responses")
}

fn read_fixture(path: &std::path::Path) -> serde_json::Value {
    serde_json::from_str(
        &std::fs::read_to_string(path).unwrap_or_else(|e| panic!("read {path:?}: {e}")),
    )
    .unwrap()
}

#[test]
fn all_50_real_responses_parse_and_validate() {
    let dir = fixture_dir();
    // `fixtures/model_responses/` is git-ignored on purpose (sampled LM Studio
    // responses contain opponent gamertags): skip on fresh checkouts incl. CI
    // instead of failing. Synthetic + inline coverage below runs everywhere.
    if !dir.is_dir() {
        eprintln!("skipping fixture test: {dir:?} not present (personal data, git-ignored)");
        return;
    }
    let mut checked = 0usize;
    let entries = std::fs::read_dir(&dir).unwrap();
    for entry in entries {
        let path = entry.unwrap().path();
        if path.extension().and_then(|e| e.to_str()) != Some("json") {
            continue;
        }
        if !path
            .file_name()
            .and_then(|n| n.to_str())
            .is_some_and(|n| n.starts_with("accepted_") || n.starts_with("malformed_"))
        {
            continue;
        }
        let data = read_fixture(&path);
        let raw = data["raw_response"].as_str().unwrap();

        let parsed = parse_and_validate_response(raw)
            .unwrap_or_else(|err| panic!("{} failed to parse/validate: {err}", path.display()));

        // Structural contract: object with track + entries array.
        assert!(parsed.get("t").is_some(), "{} missing t", path.display());
        assert!(
            parsed.get("e").is_some_and(Value::is_array),
            "{} missing e",
            path.display()
        );

        // Accepted fixtures must match the stored parsed_json exactly.
        if data["kind"] == "accepted" {
            let expected = data["parsed_json"].clone();
            assert_eq!(parsed, expected, "parsed mismatch for {}", path.display());
            assert!(
                semantic_retry_issues(&parsed).is_empty(),
                "accepted fixture with retry issues: {}",
                path.display()
            );
        }
        checked += 1;
    }
    assert!(
        checked >= 50,
        "expected at least 50 fixtures, found {checked}"
    );
}

#[test]
fn repair_pass_handles_synthetic_corruptions() {
    use forza_lmstudio::json_repair::repair_json;

    let valid = r#"{"t":"Fuji Speedway","tf":70,"w":"dry","e":[{"dr":"D","ca":"C","cl":"A","bl":"1:23.456"}]}"#;

    // trailing comma
    let repaired = repair_json(
        r#"{"t":"Fuji","tf":70,"w":"dry","e":[{"dr":"D","ca":"C","cl":"A","bl":"1:23.456"},]}"#,
    );
    assert!(parse_and_validate_response(&repaired).is_ok());
    let _ = valid;

    // prose around the object
    let wrapped = format!("Here is the JSON you asked for:\n{valid}\nHope this helps!");
    assert!(parse_and_validate_response(&wrapped).is_ok());

    // fences
    let fenced = format!("```json\n{valid}\n```");
    assert!(parse_and_validate_response(&fenced).is_ok());
}

#[test]
fn validation_rejects_bad_lap_times_and_missing_fields() {
    use forza_lmstudio::response::parse_and_validate_response;

    let bad_time =
        r#"{"t":"X","tf":70,"w":"dry","e":[{"dr":"d","ca":"c","cl":"A","bl":"not-a-time"}]}"#;
    assert!(
        parse_and_validate_response(bad_time)
            .unwrap_err()
            .contains("unparseable lap time")
    );

    let missing_field = r#"{"t":"X","tf":70,"w":"dry","e":[{"dr":"d","ca":"c","bl":"1:00.000"}]}"#;
    assert!(
        parse_and_validate_response(missing_field)
            .unwrap_err()
            .contains("missing field 'cl'")
    );

    let not_object = r#"["array"]"#;
    assert!(
        parse_and_validate_response(not_object)
            .unwrap_err()
            .contains("not a JSON object")
    );
}
