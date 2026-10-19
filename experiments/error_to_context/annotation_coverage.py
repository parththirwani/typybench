import ast
from dataclasses import dataclass


@dataclass
class CoverageDelta:
    file: str
    added_param_annotations: int
    added_return_annotations: int
    added_variable_annotations: int
    total_functions: int
    total_classes: int
    total_any_annotations: int
    total_object_annotations: int
    total_concrete_annotations: int
    untyped_functions: int
    added_any_annotations: int = 0
    added_object_annotations: int = 0
    added_concrete_annotations: int = 0

    @property
    def added_total(self) -> int:
        return self.added_param_annotations + self.added_return_annotations + self.added_variable_annotations

    @property
    def any_object_pct(self) -> float:
        total = self.added_any_annotations + self.added_object_annotations + self.added_concrete_annotations
        if total == 0:
            return 0.0
        return (self.added_any_annotations + self.added_object_annotations) / total * 100

    @property
    def untyped_func_pct(self) -> float:
        if self.total_functions == 0:
            return 0.0
        return self.untyped_functions / self.total_functions * 100


def _annotation_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _annotation_name(node.value)
    if isinstance(node, ast.Constant):
        return str(node.value)
    return None


def _annotation_kind(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            node = ast.parse(node.value, mode="eval").body
        except SyntaxError:
            pass
    names = {_annotation_name(child) for child in ast.walk(node)
             if isinstance(child, (ast.Name, ast.Attribute))}
    if "Any" in names or "any" in names:
        return "any"
    if "object" in names:
        return "object"
    return "concrete"


def count_annotations(tree: ast.AST) -> dict:
    params = 0
    returns = 0
    variables = 0
    funcs = 0
    classes = 0
    any_count = 0
    object_count = 0
    concrete_count = 0
    typed_funcs = 0

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs += 1
            has_any = False
            for arg in node.args.args + node.args.kwonlyargs + node.args.posonlyargs:
                if arg.annotation:
                    params += 1
                    kind = _annotation_kind(arg.annotation)
                    if kind == "any":
                        any_count += 1
                    elif kind == "object":
                        object_count += 1
                    else:
                        concrete_count += 1
            if node.returns:
                returns += 1
                kind = _annotation_kind(node.returns)
                if kind == "any":
                    any_count += 1
                elif kind == "object":
                    object_count += 1
                else:
                    concrete_count += 1
            if any(p for p in node.args.args + node.args.kwonlyargs + node.args.posonlyargs if p.annotation) or node.returns:
                typed_funcs += 1
        elif isinstance(node, ast.ClassDef):
            classes += 1
        elif isinstance(node, ast.AnnAssign):
            if node.annotation:
                variables += 1
                kind = _annotation_kind(node.annotation)
                if kind == "any":
                    any_count += 1
                elif kind == "object":
                    object_count += 1
                else:
                    concrete_count += 1

    return {
        "params": params, "returns": returns, "variables": variables,
        "funcs": funcs, "classes": classes,
        "any": any_count, "object": object_count, "concrete": concrete_count,
        "typed_funcs": typed_funcs,
    }


def coverage_delta(original_path: str, annotated_path: str) -> CoverageDelta | None:
    try:
        with open(original_path) as f:
            orig_tree = ast.parse(f.read())
        with open(annotated_path) as f:
            ann_tree = ast.parse(f.read())
    except (SyntaxError, FileNotFoundError):
        return None

    orig = count_annotations(orig_tree)
    ann = count_annotations(ann_tree)
    return CoverageDelta(
        file=original_path,
        added_param_annotations=ann["params"] - orig["params"],
        added_return_annotations=ann["returns"] - orig["returns"],
        added_variable_annotations=ann["variables"] - orig["variables"],
        total_functions=ann["funcs"],
        total_classes=ann["classes"],
        total_any_annotations=ann["any"],
        total_object_annotations=ann["object"],
        total_concrete_annotations=ann["concrete"],
        untyped_functions=ann["funcs"] - ann["typed_funcs"],
        added_any_annotations=max(0, ann["any"] - orig["any"]),
        added_object_annotations=max(0, ann["object"] - orig["object"]),
        added_concrete_annotations=max(0, ann["concrete"] - orig["concrete"]),
    )


def scan_baseline(baseline_dir: str, original_dir: str) -> list[CoverageDelta]:
    import os
    from pathlib import Path

    results = []
    for pyfile in sorted(Path(baseline_dir).rglob("*.py")):
        rel = pyfile.relative_to(baseline_dir)
        orig_file = os.path.join(original_dir, rel)
        if not os.path.isfile(orig_file):
            continue
        delta = coverage_delta(orig_file, str(pyfile))
        if delta:
            results.append(delta)
    return results
