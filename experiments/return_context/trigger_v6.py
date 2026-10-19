"""Use source syntax to distinguish type-bearing evidence from weak memory."""

import ast

from .select import DATA_ROOT
from .trigger_v5 import choose_action as choose_v5


def _root_name(node: ast.AST) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _has_type_bearing_evidence(case: dict) -> bool:
    path = DATA_ROOT / case["repo"] / "repo_without_types" / case["callee_file"]
    if "original_repo" in path.parts:
        raise ValueError("Typed reference is outside trigger scope")
    tree = ast.parse(path.read_text())
    matches = [node for node in tree.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
               and node.name == case["callee_symbol"]]
    if len(matches) != 1:
        raise ValueError(case["case_id"])
    imported = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.update(alias.asname or alias.name for alias in node.names)

    class Evidence(ast.NodeVisitor):
        def __init__(self):
            self.returns = []
            self.assignments = {}
            self.yields = False
            self.cast = False

        def visit_Return(self, node):
            self.returns.append(node.value)
            self.generic_visit(node)

        def visit_Yield(self, node):
            self.yields = True
            self.generic_visit(node)

        visit_YieldFrom = visit_Yield

        def visit_Call(self, node):
            self.cast |= isinstance(node.func, ast.Name) and node.func.id == "cast"
            self.generic_visit(node)

        def visit_Assign(self, node):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.assignments.setdefault(target.id, []).append(node.value)
            self.generic_visit(node)

        def visit_AnnAssign(self, node):
            if isinstance(node.target, ast.Name):
                self.assignments.setdefault(node.target.id, []).append(node)
            self.generic_visit(node)

        def visit_FunctionDef(self, node):
            return None

        visit_AsyncFunctionDef = visit_FunctionDef
        visit_Lambda = visit_FunctionDef

    found = Evidence()
    for statement in matches[0].body:
        found.visit(statement)
    if found.yields or found.cast:
        return True
    for expression in found.returns:
        if isinstance(expression, ast.Name):
            if any(isinstance(value, ast.AnnAssign) or isinstance(value, ast.Call)
                   for value in found.assignments.get(expression.id, [])):
                return True
        if isinstance(expression, ast.Call):
            fn = expression.func
            if isinstance(fn, ast.Name) and fn.id[:1].isupper():
                return True
            if isinstance(fn, ast.Attribute):
                root = _root_name(fn)
                if root and (root in imported or root[:1].isupper()):
                    return True
    return False


def choose_action(case: dict) -> str:
    first = choose_v5(case)
    if first.startswith("static:"):
        return first
    return "B" if _has_type_bearing_evidence(case) else "A"
