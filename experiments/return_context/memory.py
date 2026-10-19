"""Deterministic return-behavior memory from stripped repository source."""

import ast
import hashlib
from pathlib import Path

from .select import DATA_ROOT


MAX_MEMORY_CHARS = 1000


def _short(node: ast.AST, limit: int = 230) -> str:
    value = ast.unparse(node).replace("\n", " ")
    return value if len(value) <= limit else value[:limit - 15] + " ...[truncated]"


def build_memory(case: dict) -> tuple[str, str]:
    path = DATA_ROOT / case["repo"] / "repo_without_types" / case["callee_file"]
    if "original_repo" in path.parts:
        raise ValueError("Typed reference is outside memory scope")
    tree = ast.parse(path.read_text())
    matches = [node for node in tree.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
               and node.name == case["callee_symbol"]]
    if len(matches) != 1:
        raise ValueError(f"Ambiguous callee: {case['case_id']}")
    function = matches[0]
    returns = []
    yields = []
    assignments = []

    class Evidence(ast.NodeVisitor):
        def visit_Return(self, node):
            returns.append(node)
            self.generic_visit(node)

        def visit_Yield(self, node):
            yields.append(node)
            self.generic_visit(node)

        def visit_YieldFrom(self, node):
            yields.append(node)
            self.generic_visit(node)

        def visit_Assign(self, node):
            assignments.append(node)
            self.generic_visit(node)

        def visit_AnnAssign(self, node):
            assignments.append(node)
            self.generic_visit(node)

        def visit_FunctionDef(self, node):
            return None

        visit_AsyncFunctionDef = visit_FunctionDef
        visit_Lambda = visit_FunctionDef

    visitor = Evidence()
    for statement in function.body:
        visitor.visit(statement)

    header = f"Source: {case['callee_file']}:{function.lineno} function {function.name}"
    entries = [header]
    for decorator in function.decorator_list[:3]:
        entries.append(f"decorator: @{_short(decorator)}")
    returned_names = set()
    for node in returns:
        expression = node.value
        entries.append(f"return line {node.lineno}: {_short(expression) if expression else 'None'}")
        if expression:
            returned_names.update(child.id for child in ast.walk(expression)
                                  if isinstance(child, ast.Name))
    for node in yields:
        expression = node.value
        entries.append(f"yield line {node.lineno}: {_short(expression) if expression else 'None'}")
    if not returns and not yields:
        entries.append("No explicit return or yield; implicit return None.")
    for node in assignments:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        assigned = {child.id for target in targets for child in ast.walk(target)
                    if isinstance(child, ast.Name)}
        if assigned & returned_names:
            entries.append(f"assignment line {node.lineno}: {_short(node)}")

    selected = []
    for entry in entries:
        candidate = "\n".join(selected + [entry])
        if len(candidate) > MAX_MEMORY_CHARS:
            selected.append("[additional evidence truncated]")
            break
        selected.append(entry)
    summary = "\n".join(selected)[:MAX_MEMORY_CHARS]
    return summary, hashlib.sha256(summary.encode()).hexdigest()[:16]
