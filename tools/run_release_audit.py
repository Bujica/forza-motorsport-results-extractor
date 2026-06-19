from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_ROOT = ROOT / "output" / "release_audit"


@dataclass(frozen=True)
class CommandSpec:
    label: str
    command: list[str]
    kind: str = "generic"


def _slug(value: str) -> str:
    chars = []
    for char in value.casefold():
        if char.isalnum():
            chars.append(char)
        elif chars and chars[-1] != "_":
            chars.append("_")
    return "".join(chars).strip("_") or "step"


def _tail(text_value: str, *, lines: int = 80) -> str:
    split = text_value.splitlines()
    if len(split) <= lines:
        return text_value
    return "\n".join(split[-lines:])


def _run_git(args: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError:
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _git_context() -> dict[str, Any]:
    status = _run_git(["status", "--short"])
    return {
        "branch": _run_git(["rev-parse", "--abbrev-ref", "HEAD"]),
        "commit": _run_git(["rev-parse", "HEAD"]),
        "status_short": status.splitlines(),
        "dirty": bool(status.strip()),
    }


def _json_from_stdout(stdout: str) -> Any | None:
    stripped = stdout.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(stripped[start:end + 1])
            except json.JSONDecodeError:
                return None
    return None


def _interpret_step(kind: str, exit_code: int, stdout: str) -> dict[str, Any]:
    parsed = _json_from_stdout(stdout)
    details: dict[str, Any] = {"parsed_json": parsed}

    if kind == "db_doctor":
        checks = []
        failed_errors = []
        warnings = []
        ok = exit_code == 0
        schema_state = None
        if isinstance(parsed, dict):
            ok = bool(parsed.get("ok"))
            schema_state = parsed.get("schema_state")
            checks = list(parsed.get("checks") or [])
            failed_errors = [
                check for check in checks
                if check.get("severity") == "error" and not check.get("ok")
            ]
            warnings = [
                check for check in checks
                if check.get("severity") == "warning" and not check.get("ok")
            ]
        details.update({
            "ok": ok,
            "schema_state": schema_state,
            "failed_error_count": len(failed_errors),
            "warning_count": len(warnings),
            "failed_errors": failed_errors,
            "warnings": warnings,
        })
        return details

    if kind == "module_size":
        files = parsed.get("files") if isinstance(parsed, dict) else []
        over_budget = [
            item for item in files
            if item.get("over_budget") and not item.get("allowlisted")
        ] if isinstance(files, list) else []
        details.update({
            "ok": exit_code == 0,
            "file_count": len(files) if isinstance(files, list) else None,
            "over_budget_count": len(over_budget),
            "over_budget": over_budget[:50],
        })
        return details

    if kind == "test_selection":
        missing_tests = parsed.get("missing_tests") if isinstance(parsed, dict) else []
        details.update({
            "ok": exit_code == 0 and not missing_tests,
            "changed_file_count": len(parsed.get("changed_files") or []) if isinstance(parsed, dict) else None,
            "selected_test_count": len(parsed.get("tests") or []) if isinstance(parsed, dict) else None,
            "missing_test_count": len(missing_tests or []),
            "fallback": parsed.get("fallback") if isinstance(parsed, dict) else None,
            "selected_tests": parsed.get("tests") if isinstance(parsed, dict) else None,
            "missing_tests": missing_tests,
            "changed_files": parsed.get("changed_files") if isinstance(parsed, dict) else None,
            "unknown_forza_files": parsed.get("unknown_forza_files") if isinstance(parsed, dict) else None,
        })
        return details

    details["ok"] = exit_code == 0
    return details


def _write_step_log(report_dir: Path, index: int, spec: CommandSpec, result: dict[str, Any]) -> Path:
    log_path = report_dir / f"{index:02d}_{_slug(spec.label)}.log"
    log_path.write_text(
        "\n".join([
            f"label: {spec.label}",
            f"command: {' '.join(spec.command)}",
            f"exit_code: {result['exit_code']}",
            f"duration_seconds: {result['duration_seconds']:.3f}",
            "",
            "STDOUT",
            "------",
            result["stdout"],
            "",
            "STDERR",
            "------",
            result["stderr"],
        ]),
        encoding="utf-8",
    )
    return log_path


def _run_step(report_dir: Path, index: int, spec: CommandSpec) -> dict[str, Any]:
    started = time.perf_counter()
    completed = subprocess.run(
        spec.command,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    duration = time.perf_counter() - started
    interpreted = _interpret_step(spec.kind, int(completed.returncode), completed.stdout)
    logical_ok = bool(interpreted.get("ok", completed.returncode == 0))
    result: dict[str, Any] = {
        "label": spec.label,
        "command": spec.command,
        "kind": spec.kind,
        "exit_code": int(completed.returncode),
        "duration_seconds": duration,
        "logical_ok": logical_ok,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "stdout_tail": _tail(completed.stdout),
        "stderr_tail": _tail(completed.stderr),
        "details": interpreted,
    }
    log_path = _write_step_log(report_dir, index, spec, result)
    result["log_path"] = str(log_path.relative_to(ROOT))
    result.pop("stdout")
    result.pop("stderr")
    return result


def _select_targeted_tests(py: str, args: argparse.Namespace) -> tuple[dict[str, Any], list[str]]:
    cmd = [py, "tools/select_tests_for_changes.py", "--json", "--unknown-forza-policy", args.unknown_forza_policy]
    if args.base:
        cmd.extend(["--base", args.base])
    if not args.include_working_tree:
        cmd.append("--no-working-tree")

    completed = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        return {
            "ok": False,
            "error": completed.stderr or completed.stdout,
            "command": cmd,
        }, []
    selection = json.loads(completed.stdout)
    tests = list(selection.get("tests") or [])
    return selection, tests


def _commands(args: argparse.Namespace, report_dir: Path) -> list[CommandSpec]:
    py = sys.executable
    commands = [
        CommandSpec("Compile package", [py, "-m", "compileall", "-q", "forza"]),
        CommandSpec("Audit module size", [py, "tools/audit_module_size.py", "--format", "json"], kind="module_size"),
    ]

    if not args.skip_db:
        commands.extend([
            CommandSpec(
                "Run DB Doctor",
                [py, "-m", "forza", "maintenance", "db-doctor", "--config", args.config, "--json"],
                kind="db_doctor",
            ),
        ])

    test_scope = args.test_scope
    if args.fast:
        test_scope = "none"

    if test_scope == "full":
        commands.append(CommandSpec("Run pytest", [py, "-m", "pytest", "-q"]))
        if args.strict_warnings:
            commands.append(CommandSpec("Run pytest with ResourceWarning as error", [py, "-m", "pytest", "-q", "-W", "error::ResourceWarning"]))
    elif test_scope == "targeted":
        selection, tests = _select_targeted_tests(py, args)
        selection_path = report_dir / "targeted_test_selection.json"
        selection_path.write_text(json.dumps(selection, indent=2, sort_keys=True), encoding="utf-8")

        select_cmd = [py, "tools/select_tests_for_changes.py", "--json", "--unknown-forza-policy", args.unknown_forza_policy]
        if args.base:
            select_cmd.extend(["--base", args.base])
        if not args.include_working_tree:
            select_cmd.append("--no-working-tree")
        commands.append(CommandSpec("Select targeted tests", select_cmd, kind="test_selection"))

        if selection.get("fallback") == "full":
            commands.append(CommandSpec("Run pytest fallback full", [py, "-m", "pytest", "-q"]))
            if args.strict_warnings:
                commands.append(CommandSpec("Run pytest fallback full with ResourceWarning as error", [py, "-m", "pytest", "-q", "-W", "error::ResourceWarning"]))
        elif tests:
            commands.append(CommandSpec("Run targeted pytest", [py, "-m", "pytest", "-q", *tests]))
            if args.strict_warnings:
                commands.append(CommandSpec("Run targeted pytest with ResourceWarning as error", [py, "-m", "pytest", "-q", "-W", "error::ResourceWarning", *tests]))
        else:
            commands.append(CommandSpec("No targeted pytest selected", [py, "-c", "print('No targeted pytest files selected.')"]))

    if not args.skip_dry_run and not args.fast:
        commands.append(CommandSpec("Run application dry-run", [py, "-m", "forza", "--config", args.config, "--dry-run"]))

    return commands


def _write_markdown(summary: dict[str, Any], path: Path) -> None:
    lines = [
        "# Release audit summary",
        "",
        f"- Overall: {'PASS' if summary['overall_ok'] else 'FAIL'}",
        f"- Started: {summary['started_at']}",
        f"- Finished: {summary['finished_at']}",
        f"- Branch: `{summary['git'].get('branch') or ''}`",
        f"- Commit: `{summary['git'].get('commit') or ''}`",
        f"- Dirty working tree: `{summary['git'].get('dirty')}`",
        f"- Test scope: `{summary['options'].get('test_scope')}`",
        "",
        "## Steps",
        "",
    ]

    for step in summary["steps"]:
        status = "PASS" if step["logical_ok"] else "FAIL"
        lines.extend([
            f"### {status} — {step['label']}",
            "",
            f"- Exit code: `{step['exit_code']}`",
            f"- Duration: `{step['duration_seconds']:.3f}s`",
            f"- Log: `{step['log_path']}`",
        ])

        details = step.get("details") or {}
        if step["kind"] == "module_size":
            lines.append(f"- Files scanned: `{details.get('file_count')}`")
            lines.append(f"- Non-allowlisted files over budget: `{details.get('over_budget_count')}`")
            for item in details.get("over_budget", [])[:10]:
                lines.append(f"  - `{item.get('path')}` lines={item.get('lines')} budget={item.get('budget')}")
        elif step["kind"] == "db_doctor":
            lines.append(f"- Schema state: `{details.get('schema_state')}`")
            lines.append(f"- Failed error checks: `{details.get('failed_error_count', 0)}`")
            lines.append(f"- Warning checks: `{details.get('warning_count', 0)}`")
            for check in details.get("failed_errors", [])[:20]:
                lines.append(f"  - `{check.get('key')}` count={check.get('count')}: {check.get('detail')}")
            for check in details.get("warnings", [])[:10]:
                lines.append(f"  - warning `{check.get('key')}` count={check.get('count')}: {check.get('detail')}")
        elif step["kind"] == "test_selection":
            lines.append(f"- Changed files: `{details.get('changed_file_count')}`")
            lines.append(f"- Selected tests: `{details.get('selected_test_count')}`")
            lines.append(f"- Missing mapped tests: `{details.get('missing_test_count')}`")
            lines.append(f"- Fallback: `{details.get('fallback')}`")
            for test in (details.get("selected_tests") or [])[:30]:
                lines.append(f"  - `{test}`")

        if not step["logical_ok"]:
            if step.get("stdout_tail"):
                lines.extend(["", "<details><summary>stdout tail</summary>", "", "```text", step["stdout_tail"], "```", "</details>"])
            if step.get("stderr_tail"):
                lines.extend(["", "<details><summary>stderr tail</summary>", "", "```text", step["stderr_tail"], "```", "</details>"])
        lines.append("")

    status_lines = summary["git"].get("status_short") or []
    if status_lines:
        lines.extend(["## Git status", "", "```text", *status_lines, "```", ""])

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local release audit gates and write an uploadable evidence bundle.")
    parser.add_argument("--config", default="forza_config.ini")
    parser.add_argument("--report-root", default=str(DEFAULT_REPORT_ROOT))
    parser.add_argument("--report-dir", default=None, help="Exact report directory. Overrides --report-root.")
    parser.add_argument("--fast", action="store_true", help="Alias for --test-scope none --skip-dry-run.")
    parser.add_argument("--test-scope", choices=("none", "targeted", "full"), default="full")
    parser.add_argument("--base", default=None, help="Base ref for targeted test selection, e.g. origin/main.")
    parser.add_argument("--include-working-tree", action="store_true", default=True)
    parser.add_argument("--no-working-tree", action="store_false", dest="include_working_tree")
    parser.add_argument("--unknown-forza-policy", choices=("smoke", "full", "none"), default="smoke")
    parser.add_argument("--skip-db", action="store_true", help="Skip DB schema and DB Doctor gates.")
    parser.add_argument("--skip-dry-run", action="store_true")
    parser.add_argument("--strict-warnings", action="store_true", help="Run selected pytest scope again with ResourceWarning as error.")
    parser.add_argument("--stop-on-fail", action="store_true", help="Stop after first failed gate. By default all gates run.")
    parser.add_argument("--no-zip", action="store_true", help="Do not create a zip bundle.")
    args = parser.parse_args()

    if args.fast:
        args.test_scope = "none"
        args.skip_dry_run = True

    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir = Path(args.report_dir) if args.report_dir else Path(args.report_root) / stamp
    if not report_dir.is_absolute():
        report_dir = ROOT / report_dir
    report_dir.mkdir(parents=True, exist_ok=True)

    steps: list[dict[str, Any]] = []
    for index, spec in enumerate(_commands(args, report_dir), start=1):
        print(f"[{index}] {spec.label}")
        step = _run_step(report_dir, index, spec)
        steps.append(step)
        if not step["logical_ok"]:
            print(f"    FAIL exit={step['exit_code']} log={step['log_path']}")
            if args.stop_on_fail:
                break
        else:
            print(f"    PASS log={step['log_path']}")

    finished_at = datetime.now().astimezone().isoformat(timespec="seconds")
    overall_ok = all(step["logical_ok"] for step in steps)
    summary = {
        "overall_ok": overall_ok,
        "started_at": started_at,
        "finished_at": finished_at,
        "report_dir": str(report_dir.relative_to(ROOT)),
        "git": _git_context(),
        "options": {
            "test_scope": args.test_scope,
            "base": args.base,
            "include_working_tree": args.include_working_tree,
            "unknown_forza_policy": args.unknown_forza_policy,
            "skip_db": args.skip_db,
            "skip_dry_run": args.skip_dry_run,
            "strict_warnings": args.strict_warnings,
        },
        "steps": steps,
    }

    summary_json = report_dir / "audit_summary.json"
    summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    summary_md = report_dir / "audit_summary.md"
    _write_markdown(summary, summary_md)

    bundle_path = None
    if not args.no_zip:
        archive_base = report_dir.with_suffix("")
        bundle_path = Path(shutil.make_archive(str(archive_base), "zip", report_dir))

    print("\nRelease audit evidence")
    print(f"Overall: {'PASS' if overall_ok else 'FAIL'}")
    print(f"Directory: {report_dir.relative_to(ROOT)}")
    print(f"Summary JSON: {summary_json.relative_to(ROOT)}")
    print(f"Summary Markdown: {summary_md.relative_to(ROOT)}")
    if bundle_path is not None:
        print(f"Upload this ZIP: {bundle_path.relative_to(ROOT)}")

    return 0 if overall_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
