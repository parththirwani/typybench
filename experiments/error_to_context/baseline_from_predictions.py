"""Build an annotation-only baseline from frozen source-only parameter predictions."""

import argparse
import ast
import hashlib
import json
import shutil
from collections import defaultdict
from pathlib import Path

from experiments.parameter_context.select import DATA_ROOT
from .correction import _annotation_nodes_differ


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _insert_annotations(source: str, items: list[dict]) -> tuple[str, list[dict]]:
    tree = ast.parse(source)
    replacements = []
    rejected = []
    for item in items:
        functions = [node for node in tree.body
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and node.name == item["callee_symbol"]]
        if len(functions) != 1:
            rejected.append({"case_id": item["case_id"], "reason": "No unique top-level function"})
            continue
        function = functions[0]
        parameters = (function.args.posonlyargs + function.args.args + function.args.kwonlyargs)
        matches = [arg for arg in parameters if arg.arg == item["parameter"]]
        if len(matches) != 1 or matches[0].annotation is not None:
            rejected.append({"case_id": item["case_id"], "reason": "Parameter already typed or missing"})
            continue
        arg = matches[0]
        if arg.lineno != arg.end_lineno:
            rejected.append({"case_id": item["case_id"], "reason": "Parameter spans lines"})
            continue
        replacements.append((arg.lineno, arg.end_col_offset, item["prediction"], item["case_id"]))

    lines = source.splitlines(keepends=True)
    for lineno, end_col, annotation, _ in sorted(replacements, reverse=True):
        line = lines[lineno - 1].encode("utf-8")
        lines[lineno - 1] = (line[:end_col] + f": {annotation}".encode()
                             + line[end_col:]).decode("utf-8")
    result = "".join(lines)
    try:
        updated = ast.parse(result)
    except SyntaxError as exc:
        raise ValueError(f"Inserted annotations break syntax: {exc}") from exc
    if _annotation_nodes_differ(tree, updated):
        raise ValueError("Inserted annotations changed executable code")
    return result, rejected


def build(previous_run: Path, repo: str, output: Path) -> dict:
    source_root = DATA_ROOT / repo / "repo_without_types"
    if not source_root.is_dir() or "original_repo" in source_root.parts:
        raise FileNotFoundError(source_root)
    if output.exists() or "original_repo" in output.parts:
        raise ValueError("Output exists or enters typed reference")

    selection_bytes = (previous_run / "selection.json").read_bytes()
    rows_bytes = (previous_run / "rows.jsonl").read_bytes()
    manifest = json.loads((previous_run / "manifest.json").read_text())
    frozen = json.loads((previous_run / "predictions_frozen.json").read_text())
    if _sha256(selection_bytes) != manifest["selection_sha256"]:
        raise ValueError("Prior selection hash mismatch")
    if _sha256(rows_bytes) != frozen["rows_sha256"]:
        raise ValueError("Prior prediction freeze mismatch")
    cases = {case["case_id"]: case for case in json.loads(selection_bytes)
             if case["repo"] == repo}
    rows = [json.loads(line) for line in rows_bytes.splitlines() if line.strip()]
    annotations = defaultdict(list)
    for row in rows:
        if row["arm"] != "A" or row["case_id"] not in cases or not row["valid"]:
            continue
        case = cases[row["case_id"]]
        file = case["callee_file"]
        if Path(file).is_absolute() or ".." in Path(file).parts:
            raise ValueError(f"Unsafe relative path: {file}")
        annotations[file].append({
            "case_id": row["case_id"],
            "callee_symbol": case["callee_symbol"],
            "parameter": case["parameter"],
            "prediction": row["prediction"],
        })
    shutil.copytree(source_root, output)
    applied = 0
    rejected = []
    for file, items in sorted(annotations.items()):
        path = output / file
        original = path.read_text()
        updated, file_rejected = _insert_annotations(original, items)
        path.write_text(updated)
        applied += len(items) - len(file_rejected)
        rejected.extend(file_rejected)
    report = {
        "repo": repo,
        "source": str(source_root),
        "previous_run": str(previous_run),
        "selection_sha256": _sha256(selection_bytes),
        "predictions_sha256": _sha256(rows_bytes),
        "candidate_annotations": sum(map(len, annotations.values())),
        "applied_annotations": applied,
        "rejected": rejected,
    }
    (output / "derived_baseline_manifest.json").write_text(json.dumps(report, indent=2))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous-run", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output.exists():
        raise FileExistsError(output)
    if args.dry_run:
        print("Dry run: no repository copied or annotated")
        return 0
    print(json.dumps(build(Path(args.previous_run), args.repo, output), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
