"""Extend a provisional dev-repository baseline with predefined, untouched modules.

This operates only on repo_without_types and a copied prediction snapshot.
It never reads the typed reference repository. Run only before case selection.
"""

import argparse
import ast
import os
import shutil
from pathlib import Path

from .annotation_coverage import coverage_delta, scan_baseline
from .baseline import _annotate_file_by_defs, _check_gate, _hash_snapshot
from .cloud_client import CloudClient, ENV_KEY
from .correction import _annotation_nodes_differ
from .diagnostics import parse_mypy_lines, run_mypy


DATA_ROOT = Path("/home/too_geeky/research/typybenchdata")
TARGETS = {
    "typer": ("main.py", "models.py", "params.py", "rich_utils.py", "testing.py"),
    "pre-commit": ("git.py", "hook.py", "lang_base.py", "repository.py", "store.py", "util.py"),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-baseline", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-api-calls", type=int, default=55)
    parser.add_argument("--repo", choices=tuple(TARGETS), default="typer")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    source = DATA_ROOT / args.repo / "repo_without_types"
    package = "typer" if args.repo == "typer" else "pre_commit"
    targets = TARGETS[args.repo]

    source_baseline = Path(args.from_baseline).resolve()
    output = Path(args.output_dir).resolve() / "baseline"
    if output.exists():
        raise FileExistsError(output)
    if not source_baseline.is_dir():
        raise FileNotFoundError(source_baseline)
    if "original_repo" in output.parts or "original_repo" in source_baseline.parts:
        raise ValueError("The typed reference is outside inference scope")
    if args.max_api_calls < 1:
        raise ValueError("max-api-calls must be positive")
    if args.dry_run:
        print(f"Would copy {source_baseline} to {output} and annotate {targets}; zero API calls")
        return 0
    if not os.environ.get(ENV_KEY):
        raise RuntimeError(f"{ENV_KEY} is not set")

    shutil.copytree(source_baseline, output)
    client = CloudClient()
    calls = 0
    for name in targets:
        if calls >= args.max_api_calls:
            break
        original = source / package / name
        predicted = output / package / name
        if original.read_bytes() != predicted.read_bytes():
            raise ValueError(f"Target was already modified: {name}")
        calls = _annotate_file_by_defs(original, predicted, client, calls,
                                       args.max_api_calls, repo_root=str(output))
        if _annotation_nodes_differ(ast.parse(original.read_text()),
                                    ast.parse(predicted.read_text())):
            raise ValueError(f"Executable AST changed: {name}")
        delta = coverage_delta(str(original), str(predicted))
        if _check_gate([delta]):
            shutil.copy2(original, predicted)
            print(f"Rejected {name}: annotation quality gate", flush=True)
        else:
            print(f"Accepted {name}: +{delta.added_total} annotations", flush=True)

    _hash_snapshot(str(output))
    deltas = scan_baseline(str(output), str(source))
    gate_failures = _check_gate(deltas)
    errors = run_mypy(str(output))
    print(f"Baseline: {output}")
    print(f"Calls: {len(client.records)}; annotations: {sum(d.added_total for d in deltas)}")
    print(f"Gate failures: {gate_failures}")
    print(f"Mypy errors: {sum(' error:' in line for line in errors)}; "
          f"target diagnostics: {len(parse_mypy_lines(errors))}")
    return 0 if not gate_failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
