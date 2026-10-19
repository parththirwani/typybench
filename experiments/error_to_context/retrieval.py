import ast
import os
from dataclasses import dataclass
from typing import Optional


MAX_TOKENS = 300
MAX_CHARS_APPROX = 1200


@dataclass
class RetrievedDef:
    source_path: str
    start_line: int
    end_line: int
    symbol_name: str
    content: str
    content_hash: str
    truncation: str  # "exact" | "approx"


def _hash_content(content: str) -> str:
    import hashlib
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def resolve_import(import_name: str, source_file: str, repo_root: str) -> Optional[str]:
    repo_root = os.path.abspath(repo_root)
    source_root = os.path.join(repo_root, "src")
    if os.path.isdir(source_root):
        repo_root = source_root

    # The diagnostic is in a generated snapshot. Map its package location
    # into the allowed, untyped source tree before resolving relative imports.
    source_abs = os.path.abspath(source_file)
    if os.path.commonpath([repo_root, source_abs]) == repo_root:
        source_dir = os.path.dirname(os.path.abspath(source_file))
    else:
        # Find the longest suffix that also exists under the allowed source
        # root. This handles both src/flask/... and typer/... layouts while
        # never falling back to the generated prediction tree.
        source_parts = os.path.normpath(source_abs).split(os.sep)
        mapped = None
        for offset in range(1, len(source_parts)):
            candidate = os.path.join(repo_root, *source_parts[offset:])
            if os.path.isdir(os.path.dirname(candidate)):
                mapped = candidate
                break
        if mapped is None:
            return None
        source_dir = os.path.dirname(mapped)

    parts = import_name.split(".")
    for i in range(len(parts), 0, -1):
        prefix = ".".join(parts[:i])
        suffix = parts[i:]
        candidate = _resolve_module_path(prefix, source_dir, repo_root)
        if candidate:
            if os.path.commonpath([repo_root, os.path.abspath(candidate)]) != repo_root:
                continue
            if i == 1 and not suffix:
                return _resolve_init(candidate)
            if suffix:
                return _resolve_subname(candidate, suffix)
            return candidate

    return None


def _resolve_module_path(module: str, source_dir: str, repo_root: str) -> Optional[str]:
    parts = module.split(".")
    dir_path = os.path.join(repo_root, *parts)
    file_path = dir_path + ".py"
    if os.path.isfile(file_path):
        return file_path
    init_path = os.path.join(dir_path, "__init__.py")
    if os.path.isfile(init_path):
        return init_path
    dir_path2 = os.path.join(source_dir, *parts)
    file_path2 = dir_path2 + ".py"
    if os.path.isfile(file_path2):
        return file_path2
    init_path2 = os.path.join(dir_path2, "__init__.py")
    if os.path.isfile(init_path2):
        return init_path2
    return None


def _resolve_init(package_path: str) -> Optional[str]:
    if os.path.isdir(package_path):
        init = os.path.join(package_path, "__init__.py")
        if os.path.isfile(init):
            return init
    return package_path


def _resolve_subname(module_path: str, parts: list[str]) -> Optional[str]:
    d = os.path.dirname(module_path) if module_path.endswith(".py") else module_path
    name = parts[0]
    candidate_py = os.path.join(d, name + ".py")
    candidate_init = os.path.join(d, name, "__init__.py")
    if os.path.isfile(candidate_py):
        if len(parts) == 1:
            return candidate_py
        return _resolve_subname(candidate_py, parts[1:])
    if os.path.isfile(candidate_init):
        if len(parts) == 1:
            return candidate_init
        return _resolve_subname(candidate_init, parts[1:])
    return None


def extract_name_from_import(import_node: ast.stmt) -> list[tuple[str, Optional[str]]]:
    results = []
    if isinstance(import_node, ast.Import):
        for alias in import_node.names:
            results.append((alias.name, alias.asname))
    elif isinstance(import_node, ast.ImportFrom):
        module = import_node.module or ""
        for alias in import_node.names:
            full = f"{module}.{alias.name}" if module else alias.name
            results.append((full, alias.asname))
    return results


def resolve_symbol_from_diagnostic(
    error_line: str,
    source_file: str,
    repo_root: str,
    diag_message: str,
) -> Optional[str]:
    parts = diag_message.split()
    if not parts:
        return None
    first_word = parts[0].strip('"')
    if "." in first_word:
        return first_word
    return first_word


def extract_definition(
    filepath: str,
    symbol_name: str,
    approx_char_limit: int = MAX_CHARS_APPROX,
) -> Optional[RetrievedDef]:
    with open(filepath) as f:
        source = f.read()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == symbol_name:
                start = node.lineno
                end = getattr(node, "end_lineno", start)
                content = _extract_lines(filepath, start, end)
                truncated, truncation = _truncate(content, approx_char_limit)
                return RetrievedDef(
                    source_path=filepath,
                    start_line=start,
                    end_line=end,
                    symbol_name=symbol_name,
                    content=truncated,
                    content_hash=_hash_content(truncated),
                    truncation=truncation,
                )

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == symbol_name:
                    start = node.lineno
                    end = getattr(node, "end_lineno", start)
                    content = _extract_lines(filepath, start, end)
                    truncated, truncation = _truncate(content, approx_char_limit)
                    return RetrievedDef(
                        source_path=filepath,
                        start_line=start,
                        end_line=end,
                        symbol_name=symbol_name,
                        content=truncated,
                        content_hash=_hash_content(truncated),
                        truncation=truncation,
                    )

    return None


def find_parameter_annotation(filepath: str, symbol_name: str, parameter: str) -> Optional[int]:
    """Locate one annotated parameter in a predicted cross-file definition."""
    try:
        with open(filepath) as f:
            tree = ast.parse(f.read())
    except (OSError, SyntaxError):
        return None
    definitions = [node for node in tree.body
                   if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                   and node.name == symbol_name]
    if len(definitions) != 1:
        return None
    node = definitions[0]
    if isinstance(node, ast.ClassDef):
        constructors = [child for child in node.body
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and child.name == "__init__"]
        if len(constructors) != 1:
            return None
        node = constructors[0]
    arguments = (node.args.posonlyargs + node.args.args + node.args.kwonlyargs)
    matches = [arg for arg in arguments if arg.arg == parameter and arg.annotation is not None]
    if len(matches) != 1:
        return None
    arg = matches[0]
    if getattr(arg, "end_lineno", arg.lineno) != arg.lineno:
        return None
    return arg.lineno


def find_positional_parameter_annotation(
    filepath: str, symbol_name: str, one_based_position: int,
) -> Optional[tuple[str, int]]:
    """Map a mypy positional argument number to one annotated parameter."""
    if one_based_position < 1:
        return None
    try:
        with open(filepath) as f:
            tree = ast.parse(f.read())
    except (OSError, SyntaxError):
        return None
    definitions = [node for node in tree.body
                   if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                   and node.name == symbol_name]
    if len(definitions) != 1:
        return None
    node = definitions[0]
    if isinstance(node, ast.ClassDef):
        constructors = [child for child in node.body
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and child.name == "__init__"]
        if len(constructors) != 1:
            return None
        node = constructors[0]
        skip_self = True
    else:
        skip_self = False
    positional = node.args.posonlyargs + node.args.args
    if skip_self and positional and positional[0].arg in ("self", "cls"):
        positional = positional[1:]
    if one_based_position > len(positional):
        return None
    arg = positional[one_based_position - 1]
    if arg.annotation is None or getattr(arg, "end_lineno", arg.lineno) != arg.lineno:
        return None
    return arg.arg, arg.lineno


def _extract_lines(filepath: str, start: int, end: int) -> str:
    with open(filepath) as f:
        lines = f.readlines()
    return "".join(lines[start - 1:end])


def _truncate(content: str, approx_char_limit: int) -> tuple[str, str]:
    if len(content) <= approx_char_limit:
        return content, "exact"
    return content[:approx_char_limit] + "\n# ... truncated", "approx"
