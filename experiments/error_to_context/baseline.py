import os
import ast
import shutil
import hashlib
import textwrap
from pathlib import Path
from typing import Optional

from .cloud_client import CloudClient, MockCloudClient
from .annotation_coverage import scan_baseline
from .correction import _annotation_nodes_differ


_CONCRETE_THRESHOLD = 0.3
_MAX_ANY_OBJECT_PCT = 60.0

_SYSTEM = (
    "Add type annotations to the provided Python function. "
    "Return ONLY the annotated function block, unchanged in structure. "
    "Use specific concrete types (e.g. str, int, list[str], dict[str, int]) "
    "rather than Any or object. Look at imports and class definitions "
    "in the provided context to choose accurate types."
)

SKIP_MODULES = {"__init__", "__main__"}


def _build_context(source_path: Path, repo_root: str) -> str:
    parts = []
    try:
        with open(source_path) as f:
            src = f.read()
    except OSError:
        return ""

    tree = ast.parse(src)

    imports = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(ast.get_source_segment(src, node) or "")
    if imports:
        parts.append("# Imports in this file:\n" + "\n".join(imports))

    classes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            seg = ast.get_source_segment(src, node) or ""
            lines = seg.split("\n")
            header = lines[0] if lines else seg
            classes.append(header)
    if classes:
        parts.append("# Class definitions in this file:\n" + "\n".join(classes))

    if not parts:
        return ""
    return "Context from this module:\n" + "\n".join(parts) + "\n\n"


def build_baseline(
    repo_without_types: str,
    output_dir: str,
    client: CloudClient | MockCloudClient,
    dry_run: bool = False,
    max_api_calls: int = 500,
    gate: bool = True,
    file_allowlist: Optional[set[str]] = None,
) -> Optional[str]:
    src_dir = os.path.join(repo_without_types, "src")
    has_src_layout = os.path.isdir(src_dir)
    if not has_src_layout:
        src_dir = repo_without_types
    output_source_root = os.path.join(output_dir, "baseline", "src") if has_src_layout else os.path.join(output_dir, "baseline")

    run_dir = os.path.join(output_dir, "baseline")
    if os.path.exists(run_dir):
        if not dry_run:
            raise FileExistsError(f"Baseline already exists: {run_dir}")
        return None

    if not dry_run:
        shutil.copytree(repo_without_types, run_dir)

    if dry_run:
        return None

    py_files = sorted(Path(src_dir).rglob("*.py"))
    calls = 0
    for pyfile in py_files:
        if file_allowlist is not None and pyfile.relative_to(src_dir).as_posix() not in file_allowlist:
            continue
        stem = pyfile.stem
        if stem in SKIP_MODULES:
            rel = pyfile.relative_to(src_dir)
            target = Path(output_source_root) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pyfile, target)
            continue
        rel = pyfile.relative_to(src_dir)
        target = Path(output_source_root) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        calls = _annotate_file_by_defs(pyfile, target, client, calls, max_api_calls, repo_root=run_dir)
        if calls >= max_api_calls:
            break

    _hash_snapshot(run_dir)

    if gate:
        deltas = scan_baseline(run_dir, repo_without_types)
        violated = _check_gate(deltas)
        if violated:
            import json
            gate_report = os.path.join(run_dir, "baseline_gate_failures.json")
            with open(gate_report, "w") as f:
                json.dump(violated, f, indent=2)
            print(f"  GATE FAILURE: {len(violated)} files violate quality thresholds")
            print(f"  Gate report: {gate_report}")
            for v in violated:
                print(f"    {v['file']}: {v['reason']}")
            print(f"  Add --skip-gate to ignore or improve the baseline prompt.")
            return None

    return run_dir


def _check_gate(deltas) -> list[dict]:
    violated = []
    if sum(d.added_total for d in deltas) == 0:
        violated.append({"file": "<baseline>", "reason": "No annotations were added"})
    for d in deltas:
        if d.added_total == 0:
            continue
        reasons = []
        total_ann = d.added_concrete_annotations + d.added_any_annotations + d.added_object_annotations
        if total_ann > 0:
            any_obj_pct = (d.added_any_annotations + d.added_object_annotations) / total_ann * 100
            if any_obj_pct > _MAX_ANY_OBJECT_PCT:
                reasons.append(f"Any/object annotations {any_obj_pct:.0f}% > max {_MAX_ANY_OBJECT_PCT}%")
        concrete_pct = d.added_concrete_annotations / max(total_ann, 1)
        if total_ann > 0 and concrete_pct < _CONCRETE_THRESHOLD:
            reasons.append(f"concrete annotations {concrete_pct:.0%} < threshold {_CONCRETE_THRESHOLD:.0%}")
        if reasons:
            violated.append({"file": d.file, "reason": "; ".join(reasons)})
    return violated


def _annotate_file_by_defs(source_path: Path, target_path: Path, client, start_calls: int, max_calls: int, repo_root: str = "") -> int:
    with open(source_path) as f:
        source = f.read()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        shutil.copy2(source_path, target_path)
        return start_calls

    lines = source.split("\n")
    edits = {}
    calls = start_calls

    for node in _annotation_units(tree):
        if calls >= max_calls:
            break
        start = node.lineno
        end = getattr(node, "end_lineno", start)
        original_block = "\n".join(lines[start - 1:end])

        context = _build_context(source_path, repo_root) if repo_root else ""
        user_content = f"Add type annotations:\n```python\n{original_block}\n```"
        if context:
            user_content = context + user_content
        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user_content},
        ]
        response, _ = client.chat(messages)
        calls += 1

        annotated = _extract_code(response)
        if not annotated:
            continue

        annotated = _reindent_block(annotated, original_block)
        try:
            ast.parse(textwrap.dedent(annotated))
        except SyntaxError:
            continue

        if _is_annotation_only_block(original_block.split("\n"), annotated.split("\n")):
            edits[(start, end)] = annotated

    lines = source.split("\n")
    for (start, end), replacement in sorted(edits.items(), reverse=True):
        replacement_lines = replacement.split("\n")
        lines[start - 1:end] = replacement_lines

    result = "\n".join(lines)
    try:
        ast.parse(result)
    except SyntaxError:
        result = source
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with open(target_path, "w") as f:
        f.write(result)
    return calls


def _annotation_units(tree: ast.AST):
    """Select non-overlapping functions, including methods but not nested functions."""
    def visit_body(body):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield node
            elif isinstance(node, ast.ClassDef):
                yield from visit_body(node.body)
    yield from visit_body(getattr(tree, "body", []))


def _reindent_block(annotated: str, original_block: str) -> str:
    orig_lines = original_block.split("\n")
    if not orig_lines:
        return annotated
    leading = len(orig_lines[0]) - len(orig_lines[0].lstrip())
    return textwrap.indent(textwrap.dedent(annotated), " " * leading)


def _is_annotation_only_block(old_lines: list[str], new_lines: list[str]) -> bool:
    try:
        old_tree = ast.parse(textwrap.dedent("\n".join(old_lines)))
        new_tree = ast.parse(textwrap.dedent("\n".join(new_lines)))
    except SyntaxError:
        return False
    return not _annotation_nodes_differ(old_tree, new_tree)


def _looks_like_changeable_to_annotation(line: str) -> bool:
    stripped = line.lstrip()
    if stripped.startswith(("def ", "async def ")):
        return "->" not in stripped
    if stripped.startswith("from ") and "import" not in stripped:
        return True
    return _looks_like_annotation(line)


def _looks_like_annotation(line: str) -> bool:
    stripped = line.lstrip()
    if ":" in stripped:
        before, after = stripped.split(":", 1)
        before = before.strip()
        if before and not before.startswith(("def ", "class ", "import ", "from ", "return", "if", "elif", "else", "for", "while", "try", "except", "with", "as", "raise", "assert", "del", "pass", "break", "continue", "global", "nonlocal", "lambda", "yield")) and (" " in before or before.isidentifier()) and after.strip() and not after.strip().startswith("="):
            return True
    if "->" in stripped:
        return True
    return False


def _extract_code(response: str) -> str:
    if "```python" in response:
        start = response.index("```python") + 10
        end = response.index("```", start) if "```" in response[start:] else len(response)
        return response[start:end].strip()
    if "```" in response:
        start = response.index("```") + 3
        end = response.index("```", start) if "```" in response[start:] else len(response)
        return response[start:end].strip()
    return response.strip()


def _hash_snapshot(run_dir: str):
    hashes = {}
    for pyfile in sorted(Path(run_dir).rglob("*.py")):
        with open(pyfile, "rb") as f:
            h = hashlib.sha256(f.read()).hexdigest()[:16]
        hashes[str(pyfile.relative_to(run_dir))] = h
    with open(os.path.join(run_dir, "snapshot_hashes.json"), "w") as f:
        import json
        json.dump(hashes, f, indent=2)
