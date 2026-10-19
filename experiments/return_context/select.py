"""Select return-type cases using only TypyBench's stripped dev sources."""

import ast
import hashlib
import json
from pathlib import Path

from experiments.error_to_context.retrieval import extract_definition, resolve_import


DATA_ROOT = Path("/home/too_geeky/research/typybenchdata")
REPOSITORIES = ("flask", "typer", "pre-commit")
PACKAGE_NAMES = {
    "flask": "flask", "typer": "typer", "pre-commit": "pre_commit",
    "pdm": "pdm", "manim": "manimlib", "capa": "capa",
    "black": "black", "rich": "rich", "pip": "pip",
    "pydantic": "pydantic", "poetry": "poetry",
    "fastapi": "fastapi", "openai-python": "openai", "urllib3": "urllib3",
    "sphinx": "sphinx", "gradio": "gradio", "haystack": "haystack",
    "flake8": "flake8", "nicegui": "nicegui", "pandas-ai": "pandasai",
    "deepface": "deepface", "gptme": "gptme", "appworld": "appworld",
    "poetry": "poetry", "flake8": "flake8", "pandas-ai": "pandasai",
    "nicegui": "nicegui",
    "composio": "composio",
    "supervision": "supervision", "gpt4free": "g4f",
    "paper-qa": "paperqa", "vllm": "vllm", "agents": "livekit",
    "private-gpt": "private_gpt",
    "DB-GPT": "dbgpt", "phidata": "phi", "taipy": "taipy",
    "vnpy": "vnpy", "gpt-pilot": "core",
    "LLaMA-Factory": "llamafactory", "Pillow": "PIL",
}
MAX_FUNCTION_CHARS = 2400


def _calls_in_function(function: ast.FunctionDef) -> list[ast.Call]:
    calls = []

    class Calls(ast.NodeVisitor):
        def visit_Call(self, node):
            calls.append(node)
            self.generic_visit(node)

        def visit_FunctionDef(self, node):
            return None

        visit_AsyncFunctionDef = visit_FunctionDef
        visit_Lambda = visit_FunctionDef

    visitor = Calls()
    for statement in function.body:
        visitor.visit(statement)
    return calls


def _imports(tree: ast.Module, source: str, filepath: Path, repo_root: Path):
    direct = {}
    modules = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                local = alias.asname or alias.name
                module_candidate = f"{module}.{alias.name}" if module else alias.name
                imported_module = resolve_import(module_candidate, str(filepath), str(repo_root))
                if imported_module and Path(imported_module).stem == alias.name:
                    modules[local] = (imported_module, ast.get_source_segment(source, node) or "")
                else:
                    file = resolve_import(module, str(filepath), str(repo_root))
                    if file:
                        direct[local] = (file, alias.name, ast.get_source_segment(source, node) or "")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname or "." not in alias.name:
                    local = alias.asname or alias.name
                    file = resolve_import(alias.name, str(filepath), str(repo_root))
                    if file:
                        modules[local] = (file, ast.get_source_segment(source, node) or "")
    return direct, modules


def _resolve_call(call: ast.Call, direct, modules):
    if isinstance(call.func, ast.Name) and call.func.id in direct:
        file, symbol, statement = direct[call.func.id]
        return file, symbol, statement
    if (isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name)
            and call.func.value.id in modules):
        file, statement = modules[call.func.value.id]
        return file, call.func.attr, statement
    return None


def select_candidates(repositories=REPOSITORIES, limit: int = 60,
                      max_function_chars: int = MAX_FUNCTION_CHARS) -> list[dict]:
    candidates = []
    trees = {}
    for repo in repositories:
        source_root = DATA_ROOT / repo / "repo_without_types"
        if not source_root.is_dir():
            raise FileNotFoundError(source_root)
        import_root = (source_root / "python" if repo == "composio" else
                       source_root / "livekit-agents" if repo == "agents" else
                       source_root)
        package = source_root / "src" / PACKAGE_NAMES[repo]
        if not package.is_dir():
            package = source_root / PACKAGE_NAMES[repo]
        if not package.is_dir() and repo == "composio":
            package = source_root / "python" / "composio"
        if not package.is_dir() and repo == "agents":
            package = source_root / "livekit-agents" / "livekit"
        if not package.is_dir():
            raise FileNotFoundError(package)
        for filepath in sorted(package.rglob("*.py")):
            source = filepath.read_text()
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            direct, modules = _imports(tree, source, filepath, import_root)
            funcs = [node for node in tree.body
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
            for function in funcs:
                function_source = ast.get_source_segment(source, function) or ""
                if len(function_source) > max_function_chars:
                    continue
                for call in _calls_in_function(function):
                    found = _resolve_call(call, direct, modules)
                    if not found:
                        continue
                    def_path, symbol, import_stmt = found
                    if Path(def_path).resolve() == filepath.resolve():
                        continue
                    if def_path not in trees:
                        try:
                            trees[def_path] = ast.parse(Path(def_path).read_text())
                        except SyntaxError:
                            trees[def_path] = None
                    def_tree = trees[def_path]
                    if def_tree is None:
                        continue
                    matches = [node for node in def_tree.body
                               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                               and node.name == symbol]
                    if len(matches) != 1 or matches[0].returns is not None:
                        continue
                    definition = extract_definition(def_path, symbol, approx_char_limit=1180)
                    if not definition or not definition.content.lstrip().startswith(("def ", "async def ")):
                        continue
                    rel_file = filepath.relative_to(source_root).as_posix()
                    rel_def = Path(def_path).relative_to(source_root).as_posix()
                    case_id = f"{repo}:{rel_def}:{symbol}"
                    candidates.append({
                        "case_id": case_id,
                        "repo": repo,
                        "source_file": rel_file,
                        "function_name": function.name,
                        "function_source": function_source,
                        "import_statement": import_stmt,
                        "callee_file": rel_def,
                        "callee_symbol": symbol,
                        "callee_content": definition.content,
                        "callee_hash": definition.content_hash,
                        "callee_span": [definition.start_line, definition.end_line],
                        "truncation": definition.truncation,
                    })
    # Pick one caller per callee, then a deterministic at-most-60 case sample.
    ranked = sorted(candidates, key=lambda c: hashlib.sha256(
        f"{c['case_id']}:{c['source_file']}:{c['function_name']}".encode()).hexdigest())
    unique = []
    seen = set()
    for candidate in ranked:
        callee_key = (candidate["repo"], candidate["callee_file"], candidate["callee_symbol"])
        if callee_key in seen:
            continue
        seen.add(callee_key)
        unique.append(candidate)
    return sorted(unique, key=lambda c: hashlib.sha256(c["case_id"].encode()).hexdigest())[:limit]


if __name__ == "__main__":
    selected = select_candidates()
    print(json.dumps({"total": len(selected), "by_repo": {
        repo: sum(case["repo"] == repo for case in selected) for repo in REPOSITORIES
    }, "first_ids": [case["case_id"] for case in selected[:10]]}, indent=2))
