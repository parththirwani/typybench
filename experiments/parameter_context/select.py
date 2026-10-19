"""Select parameter-type cases from stripped source, without typed references."""

import ast
import hashlib
from pathlib import Path

from experiments.return_context.select import DATA_ROOT, _calls_in_function, select_candidates


REPOSITORIES = ("fastapi", "openai-python", "urllib3", "sphinx", "gradio", "haystack")
MAX_CALLEE_CHARS = 2400
MAX_CALLER_CHARS = 2400


def _function(tree: ast.Module, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    matches = [node for node in tree.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name]
    return matches[0] if len(matches) == 1 else None


def _imported_names(statement: str, symbol: str, module_stem: str) -> tuple[set[str], set[str]]:
    """Return local direct-function names and local module names for this import."""
    try:
        tree = ast.parse(statement)
    except SyntaxError:
        return set(), set()
    direct = set()
    modules = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == symbol:
                    direct.add(alias.asname or alias.name)
                if alias.name == module_stem:
                    modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[-1] == module_stem:
                    modules.add(alias.asname or alias.name.split(".")[0])
    return direct, modules


def _matches_call(call: ast.Call, direct: set[str], modules: set[str], symbol: str) -> bool:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id in direct
    return (isinstance(func, ast.Attribute) and func.attr == symbol
            and isinstance(func.value, ast.Name) and func.value.id in modules)


def _provided_argument(call: ast.Call, function: ast.FunctionDef | ast.AsyncFunctionDef,
                       parameter: ast.arg) -> ast.expr | None:
    if parameter.arg in {"self", "cls"}:
        return None
    for keyword in call.keywords:
        if keyword.arg == parameter.arg:
            return keyword.value
    positional = function.args.posonlyargs + function.args.args
    if parameter in positional:
        index = positional.index(parameter)
        if index < len(call.args) and not isinstance(call.args[index], ast.Starred):
            return call.args[index]
    return None


def _evidence_kind(expression: ast.expr) -> str:
    if isinstance(expression, ast.Constant) and expression.value is not None:
        return "literal"
    if isinstance(expression, (ast.List, ast.Tuple, ast.Dict, ast.Set)):
        return "container"
    if isinstance(expression, ast.Call):
        return "call"
    return "other"


def select_cases(limit: int = 120, repositories=REPOSITORIES) -> list[dict]:
    """One SHA-ranked explicitly supplied parameter per cross-file callee."""
    sources = select_candidates(repositories, limit=10000)
    candidates = []
    for base in sources:
        root = DATA_ROOT / base["repo"] / "repo_without_types"
        callee_path = root / base["callee_file"]
        caller_path = root / base["source_file"]
        callee_source = callee_path.read_text()
        caller_source = caller_path.read_text()
        callee = _function(ast.parse(callee_source), base["callee_symbol"])
        caller = _function(ast.parse(caller_source), base["function_name"])
        if callee is None or caller is None:
            continue
        callee_block = ast.get_source_segment(callee_source, callee) or ""
        caller_block = ast.get_source_segment(caller_source, caller) or ""
        if not callee_block or len(callee_block) > MAX_CALLEE_CHARS:
            continue
        if not caller_block or len(caller_block) > MAX_CALLER_CHARS:
            continue
        direct, modules = _imported_names(
            base["import_statement"], base["callee_symbol"],
            Path(base["callee_file"]).stem,
        )
        calls = [call for call in _calls_in_function(caller)
                 if _matches_call(call, direct, modules, base["callee_symbol"])]
        if not calls:
            continue
        parameters = (callee.args.posonlyargs + callee.args.args + callee.args.kwonlyargs)
        options = []
        for parameter in parameters:
            if parameter.annotation is not None or parameter.arg in {"self", "cls"}:
                continue
            for call in calls:
                value = _provided_argument(call, callee, parameter)
                if value is None:
                    continue
                expression = ast.get_source_segment(caller_source, value)
                call_text = ast.get_source_segment(caller_source, call)
                if not expression or not call_text or len(call_text) > 800:
                    continue
                options.append((parameter, expression, call_text, call.lineno,
                                _evidence_kind(value)))
        if not options:
            continue
        options.sort(key=lambda option: hashlib.sha256(
            f"{base['case_id']}:{option[0].arg}:{option[3]}".encode()).hexdigest())
        parameter, expression, call_text, call_line, evidence_kind = options[0]
        case_id = f"{base['case_id']}:{parameter.arg}"
        candidates.append({
            "case_id": case_id,
            "repo": base["repo"],
            "callee_file": base["callee_file"],
            "callee_symbol": base["callee_symbol"],
            "parameter": parameter.arg,
            "callee_block": callee_block,
            "source_file": base["source_file"],
            "caller_symbol": base["function_name"],
            "import_statement": base["import_statement"],
            "caller_block": caller_block,
            "call_text": call_text,
            "argument_expression": expression,
            "call_line": call_line,
            "evidence_kind": evidence_kind,
        })
    return sorted(candidates, key=lambda case: hashlib.sha256(case["case_id"].encode()).hexdigest())[:limit]
