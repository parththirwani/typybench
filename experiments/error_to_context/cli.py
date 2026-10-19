import os
import sys
import json
import ast
import re
import argparse
import dataclasses
from pathlib import Path

from .preflight import run_preflight
from .cloud_client import CloudClient, MockCloudClient, ENV_KEY, DEFAULT_BASE_URL, DEFAULT_MODEL
from .baseline import build_baseline
from .diagnostics import run_mypy, parse_mypy_lines, deduplicate_diagnostics, sort_diagnostics, read_source_window, Case, Diagnostic
from .retrieval import (
    resolve_import, extract_definition, find_parameter_annotation,
    find_positional_parameter_annotation, RetrievedDef,
)
from .correction import run_correction, CorrectionRow
from .summarize import summarize


DATA_PATH = "/home/too_geeky/research/typybenchdata"
FLASK_WITHOUT_TYPES = os.path.join(DATA_PATH, "flask", "repo_without_types")


def _source_repo(name: str) -> str:
    return os.path.join(DATA_PATH, name, "repo_without_types")

_MAX_CASES = 20


def _make_client(dry_run: bool = False) -> CloudClient | MockCloudClient:
    if dry_run:
        return MockCloudClient()
    return CloudClient()


def _get_run_dir(output_dir: str, dry_run: bool = False) -> str:
    run_dir = os.path.join(output_dir, "runs")
    if not dry_run:
        os.makedirs(run_dir, exist_ok=True)
    return run_dir


def _safe_dirname(s: str) -> str:
    return s.replace(":", "_").replace("/", "_").replace("\\", "_")


def cmd_preflight(args):
    all_ok, results = run_preflight(output_path=args.output_dir, dry_run=args.dry_run, repo=args.repo)
    for check, (ok, msg) in results.items():
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {check}: {msg}")
    if all_ok:
        print("Preflight: all checks passed")
        return 0
    print("Preflight: some checks failed", file=sys.stderr)
    return 1


def cmd_build_baseline(args):
    client = _make_client(dry_run=args.dry_run)
    run_dir = _get_run_dir(args.output_dir, dry_run=args.dry_run)
    source_repo = _source_repo(args.repo)
    allowlist = None
    if args.repo in ("typer", "pre-commit"):
        package = "typer" if args.repo == "typer" else "pre_commit"
        allowlist = {p.relative_to(source_repo).as_posix()
                     for p in (Path(source_repo) / package).rglob("*.py")}
    try:
        baseline_path = build_baseline(
            source_repo, run_dir, client, dry_run=args.dry_run,
            max_api_calls=args.max_api_calls, file_allowlist=allowlist,
        )
    except FileExistsError as e:
        print(f"  Baseline already exists: {e}", file=sys.stderr)
        return 1

    if args.dry_run:
        print("  [dry-run] Baseline build skipped (no API calls)")
    else:
        if baseline_path is None:
            print("  Baseline rejected by the annotation quality gate", file=sys.stderr)
            return 1
        print(f"  Baseline created at: {baseline_path}")
    print(f"  API calls made: {len(client.records)}")
    for r in client.records:
        print(f"    {r.status} | {r.model} | in={r.input_tokens} out={r.output_tokens} | {r.latency_ms:.0f}ms")
    return 0


def cmd_select_cases(args):
    baseline_path = args.baseline_dir
    if not baseline_path:
        run_dir = _get_run_dir(args.output_dir, dry_run=args.dry_run)
        baseline_path = os.path.join(run_dir, "baseline")
    if not os.path.isdir(baseline_path):
        print(f"  Baseline not found: {baseline_path}", file=sys.stderr)
        return 1

    retrieval_repo = _source_repo(args.repo)

    lines = run_mypy(baseline_path)
    all_diags = parse_mypy_lines(lines)
    all_diags = deduplicate_diagnostics(all_diags)
    all_diags = sort_diagnostics(all_diags)

    eligible = []
    excluded = []
    seen_repair_sites = set()
    for d in all_diags:
        if len(eligible) >= _MAX_CASES:
            break

        before, affected, after = read_source_window(d.file, d.line, repo_root=baseline_path)

        callee = _extract_callee(d.message, d.code)
        if not callee:
            excluded.append({"case_id": d.case_id(), "reason": "No cross-file callee identified"})
            continue
        callee_module = _resolve_import_name(callee, os.path.join(baseline_path, d.file))
        if not callee_module:
            excluded.append({"case_id": d.case_id(), "reason": f"Could not resolve import for {callee}"})
            continue
        resolved_file = resolve_import(callee_module, os.path.join(baseline_path, d.file), retrieval_repo)
        if not resolved_file:
            excluded.append({"case_id": d.case_id(), "reason": f"Could not resolve module {callee_module}"})
            continue
        retrieved = extract_definition(resolved_file, callee)
        if not retrieved:
            excluded.append({"case_id": d.case_id(), "reason": f"Could not extract definition for {callee} in {resolved_file}"})
            continue

        repair_site = {}
        if args.repo in ("typer", "pre-commit"):
            named = re.search(r'Argument "([A-Za-z_][A-Za-z_0-9]*)" to "[^"]+"', d.message)
            positional = re.search(r'Argument ([0-9]+) to "[^"]+"', d.message)
            if d.code != "arg-type" or not (named or positional):
                excluded.append({"case_id": d.case_id(), "reason": "Repair-site protocol requires a cross-file arg-type"})
                continue
            edit_rel = os.path.relpath(resolved_file, retrieval_repo)
            edit_abs = os.path.join(baseline_path, edit_rel)
            if named:
                parameter = named.group(1)
                edit_line = find_parameter_annotation(edit_abs, callee, parameter)
            else:
                found = find_positional_parameter_annotation(edit_abs, callee, int(positional.group(1)))
                parameter, edit_line = found if found else (None, None)
            if edit_line is None:
                excluded.append({"case_id": d.case_id(), "reason": "No unique annotated parameter repair site"})
                continue
            root_key = (edit_rel, edit_line, parameter)
            if root_key in seen_repair_sites:
                excluded.append({"case_id": d.case_id(), "reason": "Same parameter repair site as an earlier case"})
                continue
            seen_repair_sites.add(root_key)
            edit_before, edit_affected, edit_after = read_source_window(
                edit_rel, edit_line, context_lines=1, repo_root=baseline_path)
            repair_site = {
                "edit_file": edit_rel, "edit_line": edit_line,
                "edit_window_before": edit_before,
                "edit_source_line": edit_affected,
                "edit_window_after": edit_after,
                "parameter": parameter,
            }

        eligible.append({
            "diagnostic": (d.file, d.line, d.column, d.code, d.message),
            "case_id": d.case_id(),
            "source_line": affected,
            "window_before": before,
            "window_after": after,
            "symbol_name": callee,
            "retrieved": dataclasses.asdict(retrieved),
            **repair_site,
        })

    print(f"  Total target diagnostics: {len(all_diags)}")
    print(f"  Eligible (cross-file def resolved): {len(eligible)}")
    print(f"  Excluded: {len(excluded)}")
    for ex in excluded:
        print(f"    {ex['case_id']}: {ex['reason']}")

    out_path = os.path.join(_get_run_dir(args.output_dir, dry_run=args.dry_run), "selected_cases.json")
    if not args.dry_run:
        with open(out_path, "w") as f:
            json.dump({"eligible": eligible, "excluded": excluded, "total": len(all_diags)}, f, indent=2)
        print(f"  {len(eligible)} cases written to {out_path}")
    else:
        print(f"  [dry-run] Would write {len(eligible)} eligible cases")
    if not eligible:
        print("  No eligible cross-file cases; stopping before paid correction calls", file=sys.stderr)
        return 1
    return 0


def cmd_run_paired(args):
    client = _make_client(dry_run=args.dry_run)
    run_dir = _get_run_dir(args.output_dir, dry_run=args.dry_run)
    baseline_path = os.path.join(run_dir, "baseline")

    cases_path = args.cases or os.path.join(run_dir, "selected_cases.json")
    with open(cases_path) as f:
        data = json.load(f)
    cases_data = data.get("eligible", data) if isinstance(data, dict) else data

    results = []
    total_calls = 0
    for cd in cases_data:
        if total_calls + 2 > args.max_api_calls:
            print(f"  Reached max API calls ({args.max_api_calls}), stopping")
            break

        filepath, line, col, code, message = cd["diagnostic"]
        d = Diagnostic(file=filepath, line=line, column=col, code=code, message=message)
        case = Case(
            case_id=cd["case_id"], diagnostic=d,
            source_line=cd["source_line"],
            window_before=cd["window_before"],
            window_after=cd["window_after"],
            symbol_name=cd.get("symbol_name"),
            resolved_def_path=None, resolved_def_span=None,
            edit_file=cd.get("edit_file"), edit_line=cd.get("edit_line"),
            edit_window_before=cd.get("edit_window_before", ""),
            edit_source_line=cd.get("edit_source_line", ""),
            edit_window_after=cd.get("edit_window_after", ""),
        )

        retrieved_dict = cd.get("retrieved")
        if not retrieved_dict:
            raise ValueError(f"Case {cd['case_id']} has no cross-file definition; paired run requires both arms")
        retrieved = RetrievedDef(**retrieved_dict)

        for arm, def_info in [("A", None), ("B", retrieved)]:
            row = run_correction(case, baseline_path, run_dir, client, retrieved_def=def_info, dry_run=args.dry_run)
            total_calls = len(client.records)
            results.append(row)
            if not args.dry_run:
                safe_id = _safe_dirname(cd["case_id"])
                out_dir = os.path.join(run_dir, "corrections", f"{safe_id}_{arm}")
                os.makedirs(out_dir, exist_ok=True)
                with open(os.path.join(out_dir, "row.json"), "w") as f:
                    json.dump(dataclasses.asdict(row), f, indent=2)

    print(f"  Completed {len(results)} correction attempts")
    if not args.dry_run:
        summary = summarize(run_dir)
        print(f"  Summary: {json.dumps(summary, indent=2)}")
    print(f"  Total API calls: {len(client.records)}")
    return 0


def cmd_summarize(args):
    run_dir = _get_run_dir(args.output_dir, dry_run=args.dry_run)
    summary = summarize(run_dir)
    print(json.dumps(summary, indent=2))
    return 0


def _extract_callee(message: str, code: str) -> str | None:
    if code == "assignment":
        return None
    if code == "attr-defined":
        parts = message.split()
        if parts:
            return parts[0].strip("\"'")
    if "to" in message:
        after_to = message.split("to", 1)[1].strip()
        if after_to.startswith('"'):
            return after_to.split('"')[1]
    return None


def _resolve_import_name(name: str, source_path: str) -> str | None:
    try:
        with open(source_path) as f:
            tree = ast.parse(f.read())
    except (SyntaxError, FileNotFoundError):
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                asname = alias.asname or alias.name.split(".")[-1]
                if asname == name:
                    return alias.name
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                asname = alias.asname or alias.name
                if asname == name:
                    return node.module or ""
    return None


def _add_shared_args(parser):
    parser.add_argument("--output-dir", "-o", default="experiments/error_to_context/runs")
    parser.add_argument("--repo", choices=("flask", "typer", "pre-commit"), default="flask")
    parser.add_argument("--dry-run", action="store_true", help="Skip API calls and destructive writes")
    parser.add_argument("--max-api-calls", type=int, default=100, help="Maximum API calls to make")


def main():
    parser = argparse.ArgumentParser(description="Error-to-context retrieval experiment")

    sub = parser.add_subparsers(dest="command", required=True)

    p_pre = sub.add_parser("preflight")
    _add_shared_args(p_pre)
    p_pre.set_defaults(func=cmd_preflight)

    p_base = sub.add_parser("build-baseline")
    _add_shared_args(p_base)
    p_base.set_defaults(func=cmd_build_baseline)

    p_sel = sub.add_parser("select-cases")
    _add_shared_args(p_sel)
    p_sel.add_argument("--baseline-dir")
    p_sel.set_defaults(func=cmd_select_cases)

    p_run = sub.add_parser("run-paired")
    _add_shared_args(p_run)
    p_run.add_argument("--cases")
    p_run.set_defaults(func=cmd_run_paired)

    p_sum = sub.add_parser("summarize")
    _add_shared_args(p_sum)
    p_sum.set_defaults(func=cmd_summarize)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
