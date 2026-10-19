"""Three-case smoke test with real or mock baseline generation, capped at 12 API calls.

Usage:
  python run_smoke_test.py              # real API (requires CODEMATE_API_KEY)
  python run_smoke_test.py --mock       # mock client, no credentials needed

Tests: per-file baseline generation, mypy diagnostics, cross-file definition
resolution with pre-freeze eligibility check, paired correction with annotation-only
validation, and summarization.
"""
import os
import sys
import json
import tempfile
import shutil
import dataclasses

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from experiments.error_to_context.smoke_fixture import create_smoke_repo_without_types
from experiments.error_to_context.cloud_client import CloudClient, MockCloudClient, ENV_KEY
from experiments.error_to_context.baseline import build_baseline
from experiments.error_to_context.diagnostics import run_mypy, parse_mypy_lines, deduplicate_diagnostics, sort_diagnostics, read_source_window, Case, Diagnostic
from experiments.error_to_context.retrieval import resolve_import, extract_definition, RetrievedDef
from experiments.error_to_context.correction import run_correction
from experiments.error_to_context.summarize import summarize


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
    mock_mode = "--mock" in sys.argv

    if not mock_mode:
        key = os.environ.get(ENV_KEY)
        if not key:
            print(f"{ENV_KEY} not set, cannot run smoke test (pass --mock to use mock client)", file=sys.stderr)
            return 1

    run_dir = tempfile.mkdtemp(suffix="_smoke_run")
    print(f"=== Smoke Test ===")
    print(f"Run dir: {run_dir}")
    print(f"Max API calls: {MAX_API_CALLS}")
    print(f"Mock mode: {mock_mode}")
    print()

    # 1. Create fixture
    fixture = create_smoke_repo_without_types()
    print(f"Fixture: {fixture}")

    # 2. Build baseline (mock or real API calls)
    print("\n--- Building baseline ---")
    client = MockCloudClient() if mock_mode else CloudClient()
    os.makedirs(run_dir, exist_ok=True)
    baseline_path = build_baseline(fixture, run_dir, client, dry_run=False,
                                   max_api_calls=MAX_API_CALLS, gate=False)
    total_calls = len(client.records)
    print(f"  Baseline at: {baseline_path}")
    print(f"  API calls used: {total_calls}")
    for r in client.records:
        print(f"    {r.status} | in={r.input_tokens} out={r.output_tokens} | {r.latency_ms:.0f}ms")
    if total_calls >= MAX_API_CALLS:
        print(f"  Exceeded max API calls, aborting")
        return 1

    # 3. Run mypy on baseline, select eligible cases with resolved defs
    print("\n--- Selecting eligible cases ---")
    lines = run_mypy(baseline_path)
    all_diags = parse_mypy_lines(lines)
    all_diags = deduplicate_diagnostics(all_diags)
    all_diags = sort_diagnostics(all_diags)
    print(f"  Target diagnostics found: {len(all_diags)}")

    eligible = []
    for d in all_diags[:10]:
        if len(eligible) >= 3:
            break
        before, affected, after = read_source_window(d.file, d.line, repo_root=baseline_path)
        callee = _extract_callee(d.message, d.code)
        retrieved = None
        if callee:
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

    # 4. Run paired correction
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

        for arm, def_info in [("A", None)]:
            if len(client.records) >= MAX_API_CALLS:
                break
            row = run_correction(case, baseline_path, run_dir, client, retrieved_def=def_info, dry_run=False)
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

    # 5. Summarize
    print("\n--- Summary ---")
    summary = summarize(run_dir)
    print(json.dumps(summary, indent=2))

    # 6. API call record
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

    # 7. Baseline hash consistency check
    baseline_hashes = set(r.baseline_hash for r in results)
    if len(baseline_hashes) == 1:
        print("Baseline hash consistency: PASS")
    else:
        print(f"Baseline hash consistency: FAIL (hashes: {baseline_hashes})")

    # 8. Failure report
    failures = [r for r in results if not r.clean_correction]
    print(f"Failed attempts: {len(failures)}/{len(results)}")
    for r in failures:
        print(f"  {r.case_id} {r.arm}: errs {r.baseline_error_count}->{r.corrected_error_count} valid={r.edit_valid} target_gone={r.target_diagnostic_gone} clean={r.clean_correction} err={r.error}")

    # Estimate full-pilot cost
    print(f"\n--- Full-pilot cost estimate ---")
    if total_calls > 0:
        avg_io = total_in / total_calls
        avg_oo = total_out / total_calls
        avg_lat = total_ms / total_calls
        baseline_calls = sum(1 for r in client.records if r.prompt_hash.startswith("ece"))
        print(f"  Sampled from {total_calls} API calls:")
        print(f"  Avg input tokens: {avg_io:.0f}")
        print(f"  Avg output tokens: {avg_oo:.0f}")
        print(f"  Avg latency: {avg_lat:.0f}ms")
        baseline_count = sum(1 for r in client.records if "Add type annotations" in str(getattr(r, 'prompt_hash', '')))
        print(f"  NOTE: Token budget must be estimated from actual Flask file sizes and correction input sizes separately.")
        print(f"  Baseline: ~24 files × actual input size")
        print(f"  Correction: 20 cases × 2 arms × actual input size")

    return 0


if __name__ == "__main__":
    sys.exit(main())
