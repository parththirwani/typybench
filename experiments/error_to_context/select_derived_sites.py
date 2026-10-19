"""Freeze unique repair sites for errors added by a model-derived baseline."""

import argparse
import ast
import dataclasses
import hashlib
import json
import os
import re
from pathlib import Path

from .cli import _extract_callee, _resolve_import_name
from .diagnostics import read_source_window
from .retrieval import (
    extract_definition, find_parameter_annotation,
    find_positional_parameter_annotation, resolve_import,
)
from experiments.return_context.select import _imports, _resolve_call


DATA_ROOT = Path("/home/too_geeky/research/typybenchdata")


def _source_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for file in sorted(root.rglob("*.py")):
        digest.update(file.relative_to(root).as_posix().encode())
        digest.update(file.read_bytes())
    return digest.hexdigest()


def _definition_from_call(caller_path: Path, source_root: Path,
                          error_line: int, callee: str) -> str | None:
    """Resolve a call on the diagnostic line, including module-qualified calls."""
    try:
        source = caller_path.read_text()
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return None
    direct, modules = _imports(tree, source, caller_path, source_root)
    paths = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (node.lineno <= error_line <= getattr(node, "end_lineno", node.lineno)):
            continue
        resolved = _resolve_call(node, direct, modules)
        if resolved and resolved[1] == callee:
            paths.add(str(Path(resolved[0]).resolve()))
    return next(iter(paths)) if len(paths) == 1 else None


def select(repo: str, baseline: Path, audit_path: Path) -> dict:
    source_root = DATA_ROOT / repo / "repo_without_types"
    if not source_root.is_dir() or "original_repo" in str(source_root):
        raise FileNotFoundError(source_root)
    audit_bytes = audit_path.read_bytes()
    audit = json.loads(audit_bytes)
    if audit["repo"] != repo or Path(audit["derived_source"]).resolve() != baseline.resolve():
        raise ValueError("Audit does not match repository baseline")
    eligible = []
    excluded = []
    seen_sites = set()
    new_errors = sorted(audit["new_errors"], key=lambda e: (
        e["file"], e["line"], e["code"], e["message"]))
    for error in new_errors:
        if error["code"] != "arg-type":
            continue
        file = error["file"]
        message = error["message"]
        callee = _extract_callee(message, "arg-type")
        caller_path = baseline / file
        definition_path = (
            _definition_from_call(caller_path, source_root, error["line"], callee)
            if callee else None
        )
        if not definition_path and callee:
            module = _resolve_import_name(callee, str(caller_path))
            if module:
                definition_path = resolve_import(module, str(caller_path), str(source_root))
        if not definition_path:
            excluded.append({"file": file, "line": error["line"], "reason": "Imported callee unresolved"})
            continue
        rel_definition = Path(definition_path).relative_to(source_root).as_posix()
        if rel_definition == file:
            excluded.append({"file": file, "line": error["line"], "reason": "Not cross-file"})
            continue
        retrieved = extract_definition(definition_path, callee)
        if retrieved is None:
            excluded.append({"file": file, "line": error["line"], "reason": "Untyped definition unresolved"})
            continue
        named = re.search(r'Argument "([A-Za-z_][A-Za-z_0-9]*)" to "[^"]+"', message)
        positional = re.search(r'Argument ([0-9]+) to "[^"]+"', message)
        edit_path = baseline / rel_definition
        if named:
            parameter = named.group(1)
            edit_line = find_parameter_annotation(str(edit_path), callee, parameter)
        elif positional:
            found = find_positional_parameter_annotation(
                str(edit_path), callee, int(positional.group(1)))
            parameter, edit_line = found if found else (None, None)
        else:
            parameter = edit_line = None
        if edit_line is None:
            excluded.append({"file": file, "line": error["line"], "reason": "No unique annotated parameter"})
            continue
        site = (rel_definition, edit_line, parameter)
        if site in seen_sites:
            excluded.append({"file": file, "line": error["line"], "reason": "Repeated repair root"})
            continue
        seen_sites.add(site)
        before, affected, after = read_source_window(
            file, error["line"], repo_root=str(baseline))
        edit_before, edit_affected, edit_after = read_source_window(
            rel_definition, edit_line, context_lines=1, repo_root=str(baseline))
        case_id = f"{repo}:{rel_definition}:{callee}:{parameter}"
        eligible.append({
            "case_id": case_id,
            "diagnostic": {**error, "column": 0},
            "source_line": affected,
            "window_before": before,
            "window_after": after,
            "symbol_name": callee,
            "edit_file": rel_definition,
            "edit_line": edit_line,
            "edit_window_before": edit_before,
            "edit_source_line": edit_affected,
            "edit_window_after": edit_after,
            "parameter": parameter,
            "retrieved": dataclasses.asdict(retrieved),
        })
    return {
        "repo": repo,
        "baseline": str(baseline.resolve()),
        "baseline_source_sha256": _source_hash(baseline),
        "audit_sha256": hashlib.sha256(audit_bytes).hexdigest(),
        "eligible": eligible,
        "excluded": excluded,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--audit", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(output)
    result = select(args.repo, Path(args.baseline), Path(args.audit))
    if not args.dry_run:
        output.write_text(json.dumps(result, indent=2))
    print(f"{args.repo}: {len(result['eligible'])} unique repair sites, "
          f"{len(result['excluded'])} excluded diagnostics")
    for excluded in result["excluded"]:
        print(f"  {excluded['file']}:{excluded['line']}: {excluded['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
