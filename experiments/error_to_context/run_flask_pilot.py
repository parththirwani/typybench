"""Bounded Flask annotation pilot with the complete package as type context.

Steps:
1. Copy the complete untyped Flask repository into a temp repo.
2. Build baseline (real API calls).
3. Print baseline annotations for manual inspection.
4. Run mypy, select eligible cases, run paired correction.
5. Print results summary and per-case annotations.

Usage: CODEMATE_API_KEY=sk-... python experiments/error_to_context/run_flask_pilot.py
       python experiments/error_to_context/run_flask_pilot.py --dry-run
"""
import os
import sys
import json
import shutil
import tempfile
import dataclasses

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from experiments.error_to_context.cloud_client import CloudClient, MockCloudClient, ENV_KEY
from experiments.error_to_context.baseline import build_baseline, _check_gate
from experiments.error_to_context.annotation_coverage import scan_baseline
from experiments.error_to_context.diagnostics import run_mypy, parse_mypy_lines, deduplicate_diagnostics, sort_diagnostics, read_source_window, Case, Diagnostic
from experiments.error_to_context.retrieval import resolve_import, extract_definition
from experiments.error_to_context.correction import run_correction
from experiments.error_to_context.summarize import summarize

MAX_API_CALLS = 90
BASELINE_CALLS = 45

FLASK_SOURCE = "/home/too_geeky/research/typybenchdata/flask/repo_without_types/src/flask"
FLASK_REPO = os.path.dirname(os.path.dirname(FLASK_SOURCE))
PILOT_FILES = [
    "__init__.py",
    "helpers.py",
    "templating.py",
    "wrappers.py",
    "globals.py",
    "signals.py",
    "typing.py",
]


def _copy_pilot_repo(dest):
    shutil.copytree(FLASK_REPO, dest, dirs_exist_ok=True)
    return dest


def _safe_dirname(s: str) -> str:
    return s.replace(":", "_").replace("/", "_").replace("\\", "_")


def _extract_callee(message: str, code: str) -> str | None:
    if code == "assignment":
        return None
    if code == "attr-defined":
        parts = message.split()
        if parts:
            return parts[0].strip("'\"")
    if "to" in message:
        after_to = message.split("to", 1)[1].strip()
        if after_to.startswith('"'):
            return after_to.split('"')[1]
    return None


def _resolve_import_name(name: str, source_path: str) -> str | None:
    import ast
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
                    return (node.module or "") + "." + alias.name
    return None


def main():
    dry_run = "--dry-run" in sys.argv

    if not dry_run:
        key = os.environ.get(ENV_KEY)
        if not key:
            print(f"ERROR: {ENV_KEY} not set", file=sys.stderr)
            return 1

    run_dir = tempfile.mkdtemp(suffix="_flask_pilot")
    print(f"=== Flask Pilot (full package; bounded annotation targets) ===")
    print(f"Run dir: {run_dir}")
    print(f"Files: {PILOT_FILES}")
    if dry_run:
        print("DRY RUN: no API calls will be made")
    print()

    # 1. Copy pilot files to temp repo
    fixture = _copy_pilot_repo(run_dir)
    print(f"Fixture repo: {fixture}")
    print()

    # 2. Build baseline
    print("--- Building baseline ---")
    client = MockCloudClient() if dry_run else CloudClient()
    baseline_path = build_baseline(fixture, run_dir, client, dry_run=dry_run,
                                   max_api_calls=MAX_API_CALLS, gate=False,
                                   file_allowlist={f"flask/{name}" for name in PILOT_FILES})
    total_calls = len(client.records)
    print(f"  Baseline at: {baseline_path}")
    print(f"  API calls used: {total_calls}")
    for r in client.records:
        print(f"    {r.status} | in={r.input_tokens} out={r.output_tokens} | {r.latency_ms:.0f}ms")
    if total_calls >= MAX_API_CALLS:
        print(f"  Aborting: exceeded {MAX_API_CALLS} calls")
        return 1

    if dry_run:
        print("DRY RUN: skipping mypy, case selection, and correction")
        print("\n--- Files prepared for baseline ---")
        for fname in PILOT_FILES:
            src_path = os.path.join(FLASK_SOURCE, fname)
            with open(src_path) as f:
                lines = f.readlines()
            print(f"  {fname}: {len(lines)} lines")
        print("\nDry run complete. To run the full pilot:")
        print("  CODEMATE_API_KEY=sk-... python experiments/error_to_context/run_flask_pilot.py")
        return 0

    # 3. Baseline quality metrics
    print("\n--- Baseline quality metrics ---")
    deltas = scan_baseline(baseline_path, fixture)
    total_any = sum(d.added_any_annotations for d in deltas)
    total_obj = sum(d.added_object_annotations for d in deltas)
    total_conc = sum(d.added_concrete_annotations for d in deltas)
    total_ann = total_any + total_obj + total_conc
    total_untyped = sum(d.untyped_functions for d in deltas)
    total_funcs = sum(d.total_functions for d in deltas)
    any_obj_pct = (total_any + total_obj) / total_ann * 100 if total_ann else 0.0
    print(f"  Newly added annotations: {sum(d.added_total for d in deltas)}")
    print(f"    Concrete: {total_conc} ({total_conc / max(total_ann, 1) * 100:.0f}%)")
    print(f"    Any: {total_any} ({total_any / max(total_ann, 1) * 100:.0f}%)")
    print(f"    object: {total_obj} ({total_obj / max(total_ann, 1) * 100:.0f}%)")
    print(f"  Untyped functions: {total_untyped}/{total_funcs} ({total_untyped / max(total_funcs, 1) * 100:.0f}%)")
    for d in deltas:
        print(f"    {os.path.basename(d.file)}: +{d.added_total} anns, "
              f"any={d.added_any_annotations} obj={d.added_object_annotations} "
              f"concrete={d.added_concrete_annotations} "
              f"untyped={d.untyped_functions}/{d.total_functions}")

    violated = _check_gate(deltas)
    if violated:
        print(f"\n  GATE FAILURE: {len(violated)} files violate quality thresholds:")
        for v in violated:
            print(f"    {os.path.basename(v['file'])}: {v['reason']}")
        print("  Baseline quality insufficient for reliable case selection.")
        print("  Continuing (for inspection), but results will be unreliable.")
    print()

    # Print only changed lines; full snapshots remain in the run directory.
    print("\n--- Baseline annotation diffs ---")
    import difflib
    for fname in PILOT_FILES:
        fpath = os.path.join(baseline_path, "src", "flask", fname)
        if os.path.exists(fpath):
            print(f"\n=== {fname} ===")
            with open(os.path.join(fixture, "src", "flask", fname)) as f:
                before = f.readlines()
            with open(fpath) as f:
                after = f.readlines()
            changed = list(difflib.unified_diff(before, after, fromfile="untyped", tofile="baseline", n=0))
            for line in changed[:160]:
                print(line, end="")
            if len(changed) > 160:
                print(f"  ... {len(changed) - 160} further diff lines in saved snapshot")

    # 4. Run mypy, select cases
    print("\n--- Selecting eligible cases ---")
    lines = run_mypy(baseline_path)
    all_diags = parse_mypy_lines(lines)
    all_diags = deduplicate_diagnostics(all_diags)
    all_diags = sort_diagnostics(all_diags)
    print(f"  Target diagnostics found: {len(all_diags)}")
    for d in all_diags:
        print(f"    {d.case_id()}: {d.message}")

    eligible = []
    for d in all_diags:
        if len(eligible) >= 3:
            break
        before, affected, after = read_source_window(d.file, d.line, repo_root=baseline_path)
        callee = _extract_callee(d.message, d.code)
        if not callee:
            print(f"    SKIP {d.case_id()}: no cross-file callee")
            continue
        callee_module = _resolve_import_name(callee, os.path.join(baseline_path, d.file))
        if not callee_module:
            print(f"    SKIP {d.case_id()}: cannot resolve import for {callee}")
            continue
        resolved_file = resolve_import(callee_module, os.path.join(baseline_path, d.file), fixture)
        if not resolved_file:
            print(f"    SKIP {d.case_id()}: cannot resolve module {callee_module}")
            continue
        retrieved = extract_definition(resolved_file, callee)
        if not retrieved:
            print(f"    SKIP {d.case_id()}: cannot extract definition for {callee}")
            continue
        eligible.append({"d": d, "before": before, "affected": affected, "after": after, "retrieved": retrieved, "callee": callee})
        label = f"-> def in {retrieved.source_path}:{retrieved.start_line}" if retrieved else "(no cross-file def)"
        print(f"    OK {d.case_id()}: {d.message} {label}")

    print(f"\n  Eligible cases: {len(eligible)}")
    if not eligible:
        print("  No eligible cases, stopping")
        return 0

    # 5. Run paired correction
    print("\n--- Running paired correction ---")
    results = []
    for cd in eligible:
        d = cd["d"]
        if len(client.records) >= MAX_API_CALLS:
            break
        case = Case(
            case_id=d.case_id(), diagnostic=d,
            source_line=cd["affected"], window_before=cd["before"],
            window_after=cd["after"], symbol_name=cd["callee"],
            resolved_def_path=None, resolved_def_span=None,
        )

        for arm, def_info in [("A", None), ("B", cd["retrieved"])]:
            if len(client.records) >= MAX_API_CALLS:
                break
            row = run_correction(case, baseline_path, run_dir, client, retrieved_def=def_info, dry_run=dry_run)
            results.append(row)
            safe_id = _safe_dirname(d.case_id())
            out_dir = os.path.join(run_dir, "corrections", f"{safe_id}_{arm}")
            os.makedirs(out_dir, exist_ok=True)
            with open(os.path.join(out_dir, "row.json"), "w") as f:
                json.dump(dataclasses.asdict(row), f, indent=2)
            r = client.records[-1]
            status = "clean" if row.clean_correction else "FAIL"
            details = f"errs {row.baseline_error_count}->{row.corrected_error_count}"
            if not row.edit_valid:
                details += f" invalid_edit={row.error}"
            elif not row.target_diagnostic_gone:
                details += " target_persists"
            print(f"    {d.case_id()} Arm {arm}: {status} ({details}) in={r.input_tokens} out={r.output_tokens} {r.latency_ms:.0f}ms")

    # 6. Print per-case annotation diffs for manual review
    print("\n--- Per-case annotation diffs ---")
    for cd in eligible:
        d = cd["d"]
        for arm in ["A", "B"]:
            corr_dir = os.path.join(run_dir, "corrections", f"{_safe_dirname(d.case_id())}_{arm}")
            row_file = os.path.join(corr_dir, "row.json")
            if not os.path.exists(row_file):
                continue
            with open(row_file) as f:
                row = json.load(f)
            print(f"\n  Case: {d.case_id()} Arm {arm}  clean={row['clean_correction']}")
            src_rel = d.file
            src_original = os.path.join(baseline_path, src_rel)
            src_corrected = os.path.join(corr_dir, src_rel)
            if os.path.exists(src_original) and os.path.exists(src_corrected):
                with open(src_original) as f:
                    orig_lines = f.readlines()
                with open(src_corrected) as f:
                    corr_lines = f.readlines()
                import difflib
                diff = list(difflib.unified_diff(orig_lines, corr_lines, fromfile="baseline", tofile="corrected"))
                for dl in diff:
                    print(f"    {dl}", end="")

    # 7. Summary
    print("\n--- Summary ---")
    summary = summarize(run_dir)
    print(json.dumps(summary, indent=2))

    # 8. API calls
    print(f"\n--- API calls: {len(client.records)} / {MAX_API_CALLS} ---")
    total_in = 0
    total_out = 0
    total_ms = 0.0
    for i, r in enumerate(client.records):
        total_in += r.input_tokens or 0
        total_out += r.output_tokens or 0
        total_ms += r.latency_ms
        print(f"  {i+1}. {r.status} | in={r.input_tokens} out={r.output_tokens} | {r.latency_ms:.0f}ms | {r.error or ''}")
    print(f"\n  Totals: in={total_in} out={total_out} | {total_ms:.0f}ms ({total_ms/1000:.1f}s)")

    # 9. Baseline hash consistency
    baseline_hashes = set(r["baseline_hash"] for r in [json.load(open(os.path.join(run_dir, "corrections", f"{_safe_dirname(cd['d'].case_id())}_{arm}", "row.json"))) for cd in eligible for arm in ["A", "B"] if os.path.exists(os.path.join(run_dir, "corrections", f"{_safe_dirname(cd['d'].case_id())}_{arm}", "row.json"))])
    if len(baseline_hashes) == 1:
        print("Baseline hash consistency: PASS")
    else:
        print(f"Baseline hash consistency: FAIL (hashes: {baseline_hashes})")

    # 10. Cost estimate for full 20-case pilot
    print(f"\n--- Full-pilot cost estimate ---")
    if total_calls > 0:
        avg_io = total_in / total_calls
        avg_oo = total_out / total_calls
        avg_lat = total_ms / total_calls
        print(f"  Sampled from {total_calls} API calls:")
        print(f"  Avg input tokens: {avg_io:.0f}")
        print(f"  Avg output tokens: {avg_oo:.0f}")
        print(f"  Avg latency: {avg_lat:.0f}ms")
        print(f"  Est. 20-case pilot: ~{int(avg_io * 40 + avg_oo * 40)} tokens, ~{avg_lat * 40 / 1000:.0f}s")

    return 0


if __name__ == "__main__":
    sys.exit(main())
