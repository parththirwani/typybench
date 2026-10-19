"""Measure source-only static type candidates on already scored development runs."""

import argparse
import ast
import json
from collections import Counter, defaultdict
from pathlib import Path

from .select import DATA_ROOT


def source_features(case: dict) -> dict:
    path = DATA_ROOT / case["repo"] / "repo_without_types" / case["callee_file"]
    tree = ast.parse(path.read_text())
    functions = [node for node in tree.body
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and node.name == case["callee_symbol"]]
    if len(functions) != 1:
        raise ValueError(case["case_id"])
    function = functions[0]

    class Visit(ast.NodeVisitor):
        def __init__(self):
            self.returns = []
            self.yields = []
            self.exceptions = []
            self.assignments = []

        def visit_Return(self, node):
            self.returns.append(node.value)

        def visit_Yield(self, node):
            self.yields.append(node)

        visit_YieldFrom = visit_Yield

        def visit_Raise(self, node):
            self.exceptions.append(node)

        visit_Assert = visit_Raise

        def visit_Assign(self, node):
            self.assignments.append(node)
            self.generic_visit(node)

        def visit_AnnAssign(self, node):
            self.assignments.append(node)
            self.generic_visit(node)

        def visit_FunctionDef(self, node):
            return None

        visit_AsyncFunctionDef = visit_FunctionDef
        visit_Lambda = visit_FunctionDef

    visitor = Visit()
    for statement in function.body:
        visitor.visit(statement)

    def expression_type(node):
        if node is None or isinstance(node, ast.Constant) and node.value is None:
            return "None", "none"
        if isinstance(node, ast.Constant) and type(node.value) in (bool, str, int, float, bytes):
            return type(node.value).__name__, "literal"
        if isinstance(node, ast.JoinedStr):
            return "str", "fstring"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in ("bool", "str", "int", "float", "bytes"):
                return node.func.id, "builtin_call"
            if node.func.id == "cast" and node.args:
                return ast.unparse(node.args[0]), "cast"
            if node.func.id[:1].isupper():
                return node.func.id, "constructor"
        return None, None

    types = [expression_type(node) for node in visitor.returns]
    predicted = types[0][0] if types and all(t == types[0][0] for t, _ in types) else None
    category = ("implicit_none" if not types and not visitor.yields else
                types[0][1] if predicted else None)
    if (not predicted and visitor.returns and
            all(isinstance(node, ast.Name) and node.id == visitor.returns[0].id
                for node in visitor.returns)):
        name = visitor.returns[0].id
        assignments = []
        for node in visitor.assignments:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id == name:
                    annotation = node.annotation
                    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
                        try:
                            annotation = ast.parse(annotation.value, mode="eval").body
                        except SyntaxError:
                            pass
                    assignments.append((ast.unparse(annotation), "annassign"))
            elif isinstance(node, ast.Assign):
                if any(isinstance(target, ast.Name) and target.id == name
                       for target in node.targets):
                    value_type, value_category = expression_type(node.value)
                    assignments.append((value_type, f"{value_category}_assign"))
        if assignments and all(t == assignments[0][0] for t, _ in assignments):
            predicted, category = assignments[0]
    final_return = bool(function.body and isinstance(function.body[-1], ast.Return))
    return {"predicted": predicted, "category": category,
            "returns": len(types), "yields": len(visitor.yields),
            "exceptions": len(visitor.exceptions), "final_return": final_return}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dirs", nargs="+", type=Path)
    args = parser.parse_args()
    for run_dir in args.run_dirs:
        cases = json.loads((run_dir / "selection.json").read_text())
        scored = {case["case_id"]: case for case in json.loads(
            (run_dir / "scores.json").read_text())["cases"]}
        counts = defaultdict(Counter)
        misses = []
        for case in cases:
            result = scored[case["case_id"]]
            if not result["evaluable"]:
                continue
            features = source_features(case)
            predicted = features["predicted"]
            if not predicted:
                continue
            key = features["category"]
            counts[key]["all"] += 1
            counts[key]["correct"] += predicted == result["reference"]
            if features["final_return"]:
                counts[key]["final"] += 1
                counts[key]["final_correct"] += predicted == result["reference"]
            if predicted != result["reference"]:
                misses.append((key, case["case_id"], predicted, result["reference"],
                               features["exceptions"], features["final_return"]))
        print(json.dumps({"run": run_dir.name,
                          "counts": {k: dict(v) for k, v in counts.items()},
                          "misses": misses}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
