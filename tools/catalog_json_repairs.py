"""Catalog what json_repair actually changes on our malformed fixtures."""

import json
import sys
from pathlib import Path

from json_repair import repair_json

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "forza-rust" / "fixtures" / "model_responses"

patterns: dict[str, int] = {}
examples: dict[str, str] = {}

for path in sorted(FIX.glob("malformed_*.json")):
    data = json.loads(path.read_text(encoding="utf-8"))
    raw = data["raw_response"]
    repaired = repair_json(raw, return_objects=False)
    # crude signature of the transformation
    sig = []
    if raw.strip() != repaired.strip():
        if "```" in raw:
            sig.append("fences")
        if raw.count("'") > 0 and '"' not in raw[: raw.find("{") + 1]:
            sig.append("quotes")
        if ",}" in repaired or ",]" in repaired:
            sig.append("trailing_comma_kept_or_fixed")
    key_raw = raw[:80].replace("\n", "\\n")
    print(f"{path.name}: len {len(raw)} -> {len(repaired)}")
    print("  RAW head:", key_raw)
    print("  REP head:", repaired[:80].replace(chr(10), "\\n"))

print("\n--- also verify accepted fixtures round-trip via plain json.loads after fence strip ---")
ok = bad = 0
for path in sorted(FIX.glob("accepted_*.json")):
    data = json.loads(path.read_text(encoding="utf-8"))
    raw = data["raw_response"]
    text = raw.strip()
    import re
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()
    try:
        obj = json.loads(text)
        same = json.dumps(obj, ensure_ascii=False, sort_keys=True) == json.dumps(
            json.loads(data["parsed_json"]), ensure_ascii=False, sort_keys=True
        )
        ok += 1 if same else 0
        if not same:
            bad += 1
            print("MISMATCH:", path.name)
    except Exception as exc:
        bad += 1
        print("PLAIN PARSE FAIL:", path.name, exc)
print(f"accepted strict-parse identical: {ok}, mismatch/fail: {bad}")
