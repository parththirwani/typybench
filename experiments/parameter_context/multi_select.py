"""Source-only index of cross-file argument uses for parameter-memory cases."""

import ast
import hashlib
from collections import defaultdict
from pathlib import Path

from experiments.return_context.select import (
    DATA_ROOT, PACKAGE_NAMES, _calls_in_function, _imports, _resolve_call,
    select_candidates,
)
from .select import _evidence_kind, _function, _provided_argument, MAX_CALLEE_CHARS


REPOSITORIES = ("flake8", "nicegui", "pandas-ai", "deepface", "gptme", "appworld")
MAX_MEMORY_CHARS = 1200


def _package_root(repo: str) -> Path:
    root = DATA_ROOT / repo / "repo_without_types"
    source = root / "src" / PACKAGE_NAMES[repo]
    return source if source.is_dir() else root / PACKAGE_NAMES[repo]


def _producer_line(function: ast.FunctionDef | ast.AsyncFunctionDef,
                   call: ast.Call, value: ast.expr, source: str) -> str | None:
    if not isinstance(value, ast.Name):
        return None
    matches = []
    for statement in function.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)) or statement.lineno >= call.lineno:
            continue
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        if any(isinstance(target, ast.Name) and target.id == value.id for target in targets):
            segment = ast.get_source_segment(source, statement) or ""
            if "\n" not in segment and len(segment) <= 230:
                matches.append((statement.lineno, segment))
    return max(matches)[1] if matches else None


def select_multi_cases(repositories=REPOSITORIES, limit: int = 120,
                       min_calls: int = 2) -> list[dict]:
    """Select one parameter per callee with at least `min_calls` cross-file uses."""
    base_candidates = select_candidates(repositories, limit=10000)
    targets = {}
    for base in base_candidates:
        root = DATA_ROOT / base["repo"] / "repo_without_types"
        callee_path = (root / base["callee_file"]).resolve()
        source = callee_path.read_text()
        try:
            function = _function(ast.parse(source), base["callee_symbol"])
        except SyntaxError:
            continue
        if function is None:
            continue
        block = ast.get_source_segment(source, function) or ""
        if not block or len(block) > MAX_CALLEE_CHARS:
            continue
        parameters = [arg for arg in (function.args.posonlyargs + function.args.args
                                      + function.args.kwonlyargs)
                      if arg.annotation is None and arg.arg not in {"self", "cls"}]
        if parameters:
            targets[(base["repo"], callee_path, base["callee_symbol"])] = (
                base, function, block, parameters,
            )

    evidence = defaultdict(list)
    for repo in repositories:
        root = DATA_ROOT / repo / "repo_without_types"
        for filepath in sorted(_package_root(repo).rglob("*.py")):
            source = filepath.read_text()
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            direct, modules = _imports(tree, source, filepath, root)
            for caller in tree.body:
                if not isinstance(caller, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for call in _calls_in_function(caller):
                    resolved = _resolve_call(call, direct, modules)
                    if not resolved:
                        continue
                    def_path, symbol, _ = resolved
                    key = (repo, Path(def_path).resolve(), symbol)
                    if key not in targets or key[1] == filepath.resolve():
                        continue
                    _, function, _, parameters = targets[key]
                    call_text = ast.get_source_segment(source, call) or ""
                    if not call_text or len(call_text) > 450:
                        continue
                    for parameter in parameters:
                        value = _provided_argument(call, function, parameter)
                        if value is None:
                            continue
                        argument = ast.get_source_segment(source, value) or ""
                        if not argument or len(argument) > 180:
                            continue
                        evidence[(key, parameter.arg)].append({
                            "source_file": filepath.relative_to(root).as_posix(),
                            "caller": caller.name,
                            "line": call.lineno,
                            "call": call_text,
                            "argument": argument,
                            "producer": _producer_line(caller, call, value, source),
                            "kind": _evidence_kind(value),
                        })

    selected = []
    for (key, parameter), items in evidence.items():
        deduped = {(item["source_file"], item["line"], item["argument"]): item
                   for item in items}
        if len(deduped) < min_calls:
            continue
        base, _, block, _ = targets[key]
        ranked = sorted(deduped.values(), key=lambda item: hashlib.sha256(
            f"{item['source_file']}:{item['line']}:{item['argument']}".encode()).hexdigest())
        memory_lines = []
        for item in ranked:
            line = (f"{item['source_file']}:{item['line']} in {item['caller']}: "
                    f"{item['call']} ; {parameter} = {item['argument']}")
            if item["producer"]:
                line += f" ; prior assignment: {item['producer']}"
            if len("\n".join(memory_lines + [line])) > MAX_MEMORY_CHARS:
                break
            memory_lines.append(line)
            if len(memory_lines) == 5:
                break
        if len(memory_lines) < min_calls:
            continue
        selected.append({
            "case_id": f"{base['case_id']}:{parameter}",
            "repo": base["repo"],
            "callee_file": base["callee_file"],
            "callee_symbol": base["callee_symbol"],
            "parameter": parameter,
            "callee_block": block,
            "memory": "\n".join(memory_lines),
            "memory_calls": len(memory_lines),
            "available_calls": len(deduped),
        })
    ranked = sorted(selected, key=lambda case: hashlib.sha256(case["case_id"].encode()).hexdigest())
    unique = []
    seen = set()
    for case in ranked:
        key = (case["repo"], case["callee_file"], case["callee_symbol"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(case)
    return unique[:limit]
