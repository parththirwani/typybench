"""Synthetic cross-file pilot — baseline annotation + Arm A/B correction.

Flow: typeless fixture → per-def baseline → mypy diagnostics → 
cross-file retrieval → paired JSON-patch correction → summary.

Verifies:
  - Baseline adds annotations (coverage delta > 0)
  - At least one cross-file arg-type diagnostic survives baseline
  - Arm A (error-only) and Arm B (error + def) both executed
  - Arm B row has non-null retrieved_hash

Usage:
  CODEMATE_API_KEY=sk-... python experiments/error_to_context/run_synthetic_pilot.py
  python experiments/error_to_context/run_synthetic_pilot.py --dry-run
"""
import os
import sys
import json
import tempfile
import dataclasses

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from experiments.error_to_context.synthetic_fixtures import create_typeless_cross_file_fixture
from experiments.error_to_context.cloud_client import CloudClient, MockCloudClient, ENV_KEY
from experiments.error_to_context.baseline import build_baseline
from experiments.error_to_context.diagnostics import run_mypy, parse_mypy_lines, deduplicate_diagnostics, sort_diagnostics, read_source_window, Case
from experiments.error_to_context.retrieval import resolve_import, extract_definition
from experiments.error_to_context.correction import run_correction
from experiments.error_to_context.summarize import summarize
from experiments.error_to_context.annotation_coverage import scan_baseline


MAX_API_CALLS = 12


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
                    return node.module or ""
    return None


def main():
    dry_run = "--dry-run" in sys.argv

    if not dry_run:
        key = os.environ.get(ENV_KEY)
        if not key:
            print(f"ERROR: {ENV_KEY} not set", file=sys.stderr)
            return 1

    run_dir = tempfile.mkdtemp(suffix="_synthetic_pilot")
    print("=== Synthetic Cross-File Pilot ===")
    print(f"Run dir: {run_dir}")
    print(f"Dry run: {dry_run}")
    print(f"Max API calls: {MAX_API_CALLS}")
    print()

    # 1. Create typeless fixture — untyped defs that should gain annotations
    fixture = create_typeless_cross_file_fixture()
    print(f"Fixture: {fixture}")
    for rel in ["src/app.py", "src/mylib/models.py", "src/mylib/__init__.py"]:
        path = os.path.join(fixture, rel)
        if os.path.isfile(path):
            with open(path) as f:
                print(f"  {rel}:")
                for i, line in enumerate(f.read().split("\n"), 1):
                    print(f"    {i}: {line}")

    # 2. Build baseline — per-def annotation
    print("\n--- Building baseline (per-def annotations) ---")
    client = MockCloudClient() if dry_run else CloudClient()
    os.makedirs(run_dir, exist_ok=True)
    baseline_path = build_baseline(fixture, run_dir, client, dry_run=dry_run, max_api_calls=MAX_API_CALLS)
    total_calls = len(client.records)
    print(f"  Baseline at: {baseline_path}")
    print(f"  API calls used: {total_calls}")
    for r in client.records:
        print(f"    {r.status} | in={r.input_tokens} out={r.output_tokens} | {r.latency_ms:.0f}ms")
    if not dry_run and baseline_path is None:
        print("Baseline did not pass the annotation quality gate; no correction cases will be run")
        return 1
    if total_calls >= MAX_API_CALLS:
        print("  Exceeded max API calls, aborting")
        return 1

    # 3. Coverage report
    if not dry_run and baseline_path:
        print("\n--- Annotation coverage delta ---")
        deltas = scan_baseline(baseline_path, fixture)
        total_added = 0
        for d in deltas:
            print(f"  {d.file}: +{d.added_total} annotations ({d.added_param_annotations}p +{d.added_return_annotations}r +{d.added_variable_annotations}v / {d.total_functions}fn {d.total_classes}cls)")
            total_added += d.added_total
        print(f"  Total annotations added: {total_added}")

    if dry_run:
        print("DRY RUN: skipping case selection and correction")
        print("\nExpected: baseline adds annotations, mypy finds arg-type errors")
        print("To run the full pilot:")
        print("  CODEMATE_API_KEY=sk-... python experiments/error_to_context/run_synthetic_pilot.py")
        return 0

    # 4. Run mypy on baseline, select eligible cases
    print("\n--- Selecting eligible cases ---")
    lines = run_mypy(baseline_path)
    all_diags = parse_mypy_lines(lines)
    all_diags = deduplicate_diagnostics(all_diags)
    all_diags = sort_diagnostics(all_diags)
    print(f"  Target diagnostics found: {len(all_diags)}")
    for d in all_diags:
        print(f"    {d.case_id()}: {d.message}")

    eligible = []
    for d in all_diags[:10]:
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
        if retrieved:
            print(f"    OK {d.case_id()}: {d.message} -> def in {retrieved.source_path}:{retrieved.start_line}")
        else:
            print(f"    OK {d.case_id()}: {d.message} (no cross-file def needed)")

    print(f"\n  Eligible cases: {len(eligible)}")
    if not eligible:
        print("  No eligible cases, stopping")
        return 0

    # 5. Run paired correction with JSON patch format
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

    # 6. Summary
    print("\n--- Summary ---")
    summary = summarize(run_dir)
    print(json.dumps(summary, indent=2))
    print(f"\n  arm_a_total == 1: {summary['arm_a_total'] == 1}")
    print(f"  arm_b_total == 1: {summary['arm_b_total'] == 1}")

    # 7. Verify Arm B has retrieved_hash
    b_rows = [r for r in results if r.arm == "B" and r.retrieved_hash]
    print(f"  Arm B rows with retrieved_hash: {len(b_rows)}/{len([r for r in results if r.arm == 'B'])}")
    b_rows_all = [r for r in results if r.arm == "B"]
    a_rows_all = [r for r in results if r.arm == "A"]
    if b_rows_all and a_rows_all:
        print(f"  Arm A hashes differ from Arm B: {all(a.prompt_hash != b.prompt_hash for a in a_rows_all for b in b_rows_all)}")

    # 8. API call record
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

    # 9. Failure report
    failures = [r for r in results if not r.clean_correction]
    print(f"\nFailed attempts: {len(failures)}/{len(results)}")
    for r in failures:
        print(f"  {r.case_id} {r.arm}: errs {r.baseline_error_count}->{r.corrected_error_count} valid={r.edit_valid} target_gone={r.target_diagnostic_gone} clean={r.clean_correction} err={r.error}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
