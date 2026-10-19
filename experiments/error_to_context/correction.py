import os
import ast
import json
import shutil
import hashlib
import copy
from dataclasses import dataclass, asdict
from typing import Optional
from pathlib import Path

from .cloud_client import CloudClient, MockCloudClient
from .diagnostics import Case, Diagnostic, run_mypy, parse_mypy_lines, _ERROR_LINE_RE
from .retrieval import RetrievedDef


CORRECT_SYSTEM_PROMPT = (
    "You are a Python type annotation fixer. Given a mypy error and the affected code, "
    "output a JSON patch of the form {\"line\": <int>, \"replacement\": \"<line text>\"} with the "
    "minimal single-line type annotation fix. The error line may be executable code: "
    "in that case, edit the annotated declaration in the numbered context, not the executable line. "
    "Do NOT change any executable logic. "
    "Do NOT add imports. Output ONLY valid JSON, no markdown."
)

@dataclass
class CorrectionRow:
    case_id: str
    arm: str
    baseline_hash: str
    prompt_hash: str
    retrieved_hash: Optional[str]
    model_response_id: Optional[str]
    edit_valid: bool
    baseline_error_count: int
    corrected_error_count: int
    target_diagnostic_gone: bool
    clean_correction: bool
    usage_input_tokens: Optional[int]
    usage_output_tokens: Optional[int]
    latency_ms: float
    error: Optional[str] = None


def run_correction(
    case: Case,
    baseline_dir: str,
    output_dir: str,
    client: CloudClient | MockCloudClient,
    retrieved_def: Optional[RetrievedDef] = None,
    dry_run: bool = False,
    mypy_target: Optional[str] = None,
    baseline_errors: Optional[list[Diagnostic]] = None,
) -> CorrectionRow:
    arm = "B" if retrieved_def else "A"
    safe_id = _safe_dirname(case.case_id)
    case_dir = os.path.join(output_dir, "corrections", f"{safe_id}_{arm}")

    if not dry_run:
        if os.path.exists(case_dir):
            raise FileExistsError(f"Correction artifact already exists: {case_dir}")
        shutil.copytree(baseline_dir, case_dir)

    baseline_hash = _dir_hash(baseline_dir)

    baseline_errors_all = (baseline_errors if baseline_errors is not None else (
        (_run_and_parse_all(baseline_dir, mypy_target)
         if mypy_target is not None else _run_and_parse_all(baseline_dir))
        if not dry_run else []
    ))
    baseline_error_count = len(baseline_errors_all)
    target_in_baseline = any(
        _matches_target(e, case.diagnostic) for e in baseline_errors_all
    )

    if dry_run:
        return CorrectionRow(
            case_id=case.case_id, arm=arm, baseline_hash=baseline_hash,
            prompt_hash="dry-run", retrieved_hash=None,
            model_response_id=None, edit_valid=True,
            baseline_error_count=baseline_error_count,
            corrected_error_count=baseline_error_count,
            target_diagnostic_gone=False, clean_correction=True,
            usage_input_tokens=None, usage_output_tokens=None,
            latency_ms=0.0,
        )

    src_rel = case.edit_file or _find_src_relative(case, baseline_dir)
    src_path = os.path.join(baseline_dir, src_rel)
    if not os.path.isfile(src_path):
        return CorrectionRow(
            case_id=case.case_id, arm=arm, baseline_hash=baseline_hash,
            prompt_hash="", retrieved_hash=None,
            model_response_id=None, edit_valid=False,
            baseline_error_count=baseline_error_count,
            corrected_error_count=baseline_error_count,
            target_diagnostic_gone=False, clean_correction=False,
            usage_input_tokens=None, usage_output_tokens=None,
            latency_ms=0.0, error=f"Source file not found: {src_rel}",
        )

    with open(src_path) as f:
        original_source = f.read()

    context_lines = case.window_before.splitlines() + [case.source_line.rstrip("\n")] + case.window_after.splitlines()
    first_line = case.diagnostic.line - len(case.window_before.splitlines())
    numbered_context = "\n".join(
        f"{number}: {line}" for number, line in enumerate(context_lines, start=first_line)
    )
    prompt_text = (
        f"mypy error: {case.diagnostic.message} [{case.diagnostic.code}] "
        f"at {case.diagnostic.file}:{case.diagnostic.line}\n"
        f"Numbered context (choose a line with an annotation):\n{numbered_context}"
    )
    if case.edit_file and case.edit_line:
        edit_lines = (case.edit_window_before.splitlines()
                      + [case.edit_source_line.rstrip("\n")]
                      + case.edit_window_after.splitlines())
        edit_start = case.edit_line - len(case.edit_window_before.splitlines())
        edit_context = "\n".join(
            f"{number}: {line}" for number, line in enumerate(edit_lines, start=edit_start)
        )
        prompt_text += (
            f"\nEdit ONLY the annotated parameter line at {case.edit_file}:{case.edit_line}. "
            f"Do not edit the call site.\nRepair-site context:\n{edit_context}"
        )
    messages = [
        {"role": "system", "content": CORRECT_SYSTEM_PROMPT},
    ]
    user_msg = prompt_text
    if retrieved_def:
        user_msg += f"\nRelevant definition:\n```python\n{retrieved_def.content}\n```"
    messages.append({"role": "user", "content": user_msg})

    prompt_hash = hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()[:16]
    if not target_in_baseline:
        return CorrectionRow(
            case_id=case.case_id, arm=arm, baseline_hash=baseline_hash,
            prompt_hash=prompt_hash,
            retrieved_hash=retrieved_def.content_hash if retrieved_def else None,
            model_response_id=None, edit_valid=False,
            baseline_error_count=baseline_error_count,
            corrected_error_count=baseline_error_count,
            target_diagnostic_gone=False, clean_correction=False,
            usage_input_tokens=None, usage_output_tokens=None, latency_ms=0.0,
            error="Target diagnostic is absent from the frozen baseline",
        )
    response, record = client.chat(messages)

    corrected_source, edit_valid, error_text = _apply_valid_edit(
        original_source, case.edit_line or case.diagnostic.line, response,
        allowed_line=case.edit_line,
        target_function=case.symbol_name if case.edit_file else None,
        target_parameter=case.repair_parameter,
    )

    if not edit_valid:
        error_text = f"raw_response={repr(response[:200])} {error_text}"

    if edit_valid:
        target_path = os.path.join(case_dir, src_rel)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, "w") as f:
            f.write(corrected_source)

    corrected_errors_all = (
        (_run_and_parse_all(case_dir, mypy_target)
         if mypy_target is not None else _run_and_parse_all(case_dir))
        if edit_valid else baseline_errors_all
    )
    corrected_error_count = len(corrected_errors_all)

    target_gone = False
    if edit_valid:
        target_gone = not any(
            _matches_target(e, case.diagnostic) for e in corrected_errors_all
        )

    clean = edit_valid and target_gone and corrected_error_count <= baseline_error_count

    return CorrectionRow(
        case_id=case.case_id,
        arm=arm,
        baseline_hash=baseline_hash,
        prompt_hash=prompt_hash,
        retrieved_hash=retrieved_def.content_hash if retrieved_def else None,
        model_response_id=record.response_id,
        edit_valid=edit_valid,
        baseline_error_count=baseline_error_count,
        corrected_error_count=corrected_error_count,
        target_diagnostic_gone=target_gone,
        clean_correction=clean,
        usage_input_tokens=record.input_tokens,
        usage_output_tokens=record.output_tokens,
        latency_ms=record.latency_ms,
        error=error_text,
    )


def _run_and_parse_all(repo_path: str, mypy_target: Optional[str] = None) -> list[Diagnostic]:
    lines = (run_mypy(repo_path, target_rel=mypy_target)
             if mypy_target is not None else run_mypy(repo_path))
    result = []
    repo_abs = os.path.abspath(repo_path)
    for line in lines:
        m = _ERROR_LINE_RE.match(line)
        if not m:
            continue
        filepath, line_str, message, code = m.groups()
        norm = os.path.normpath(filepath)
        if os.path.isabs(norm) and norm.startswith(repo_abs):
            norm = os.path.relpath(norm, repo_abs)
        try:
            line_no = int(line_str)
        except ValueError:
            continue
        result.append(Diagnostic(
            file=norm,
            line=line_no,
            column=0,
            code=code,
            message=message.strip(),
        ))
    return result


def _matches_target(diag: Diagnostic, target: Diagnostic) -> bool:
    relay = _relativize(diag.file)
    rel_t = _relativize(target.file)
    return diag.code == target.code and relay == rel_t and diag.message == target.message


def _relativize(path: str) -> str:
    norm = os.path.normpath(path)
    if os.path.isabs(norm):
        parts = norm.split(os.sep)
        for marker in ("baseline", "corrections"):
            if marker in parts:
                idx = parts.index(marker)
                remaining = parts[idx + 1:]
                if marker == "corrections" and len(remaining) > 1:
                    remaining = remaining[1:]
                return os.sep.join(remaining)
    return norm


def _annotation_nodes_differ(orig_node: ast.AST, repl_node: ast.AST) -> bool:
    orig = _strip_annotations(copy.deepcopy(orig_node))
    repl = _strip_annotations(copy.deepcopy(repl_node))
    return ast.dump(orig) != ast.dump(repl)


def _strip_annotations(node: ast.AST) -> ast.AST:
    class _AnnotationStripper(ast.NodeTransformer):
        def visit_arg(self, node: ast.arg) -> ast.arg:
            node.annotation = None
            return node

        def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
            node.returns = None
            node.type_comment = None
            self.generic_visit(node)
            return node

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AsyncFunctionDef:
            node.returns = None
            node.type_comment = None
            self.generic_visit(node)
            return node

        def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.Assign:
            value = node.value if node.value else ast.Constant(value=None)
            return ast.Assign(targets=[node.target], value=value, lineno=node.lineno, type_comment=None)

        def visit_Assign(self, node: ast.Assign) -> ast.Assign:
            node.type_comment = None
            return node

    return _AnnotationStripper().visit(node)


def _parameter_annotation(tree: ast.Module, function_name: str,
                          parameter_name: str) -> ast.expr | None:
    functions = [node for node in tree.body
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and node.name == function_name]
    if len(functions) != 1:
        return None
    args = functions[0].args
    parameters = args.posonlyargs + args.args + args.kwonlyargs
    matches = [arg for arg in parameters if arg.arg == parameter_name]
    return matches[0].annotation if len(matches) == 1 else None


def _apply_valid_edit(original_source: str, line_no: int, response: str,
                      allowed_line: Optional[int] = None,
                      target_function: Optional[str] = None,
                      target_parameter: Optional[str] = None) -> tuple[Optional[str], bool, Optional[str]]:
    cleaned = _extract_json_patch(response)
    if cleaned is None:
        return None, False, "Could not parse JSON patch from response"

    target_line, replacement = cleaned
    if allowed_line is not None and target_line != allowed_line:
        return None, False, f"Patch line {target_line} is outside frozen repair site {allowed_line}"
    lines = original_source.split("\n")
    if target_line < 1 or target_line > len(lines):
        return None, False, f"Patch line {target_line} out of range [1, {len(lines)}]"

    if replacement == lines[target_line - 1]:
        return None, False, "Patch makes no annotation change"

    result = list(lines)
    result[target_line - 1] = replacement
    joined = "\n".join(result)

    try:
        original_tree = ast.parse(original_source)
        updated_tree = ast.parse(joined)
    except SyntaxError as e:
        return None, False, f"Result file has syntax error: {e}"

    if _annotation_nodes_differ(original_tree, updated_tree):
        return None, False, "Replacement changes executable code, not just annotations"

    if target_function and target_parameter:
        original_annotation = _parameter_annotation(
            original_tree, target_function, target_parameter)
        updated_annotation = _parameter_annotation(
            updated_tree, target_function, target_parameter)
        if updated_annotation is None:
            return None, False, "Repair removes the target parameter annotation"
        if (original_annotation is not None
                and ast.dump(original_annotation) == ast.dump(updated_annotation)):
            return None, False, "Repair does not change the target parameter annotation"

    return joined, True, None


def _extract_json_patch(response: str) -> Optional[tuple[int, str]]:
    import json
    cleaned = response.strip()
    if cleaned.startswith("```"):
        for marker in ("```json", "```"):
            if marker in cleaned:
                start = cleaned.index(marker) + len(marker)
                end = cleaned.index("```", start) if "```" in cleaned[start:] else len(cleaned)
                cleaned = cleaned[start:end].strip()
    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict) or "line" not in obj or "replacement" not in obj:
        return None
    if not isinstance(obj["line"], int) or isinstance(obj["line"], bool):
        return None
    if not isinstance(obj["replacement"], str):
        return None
    return obj["line"], obj["replacement"]


def _line_is_changeable_to_annotation(line: str) -> bool:
    stripped = line.lstrip()
    if stripped.startswith("def ") or stripped.startswith("async def "):
        return "->" not in stripped
    if stripped.startswith("from ") and "import" not in stripped:
        return True
    return _line_is_annotation(line)


def _line_is_annotation(line: str) -> bool:
    stripped = line.lstrip()
    if "->" in stripped:
        return True
    if ":" not in stripped:
        return False
    before, after = stripped.split(":", 1)
    before = before.strip()
    after = after.strip()
    if not before:
        return False
    if not after or after.startswith(("=", ",", ")", "]")):
        return False
    control_keywords = {"if", "elif", "else", "for", "while", "try", "except",
                        "with", "class", "def", "return", "yield", "raise",
                        "assert", "pass", "break", "continue", "import",
                        "from", "as", "del", "global", "nonlocal", "lambda"}
    kw = before.split()[0] if before.split() else ""
    if kw in control_keywords:
        return False
    return True


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


def _dir_hash(path: str) -> str:
    h = hashlib.sha256()
    for pyfile in sorted(Path(path).rglob("*.py")):
        with open(pyfile, "rb") as f:
            h.update(f.read())
    return h.hexdigest()[:16]


def _find_src_relative(case: Case, baseline_dir: str) -> str:
    abs_file = os.path.abspath(case.diagnostic.file)
    abs_base = os.path.abspath(baseline_dir)
    if abs_file.startswith(abs_base):
        return os.path.relpath(abs_file, abs_base)
    return case.diagnostic.file


def _safe_dirname(case_id: str) -> str:
    return case_id.replace(":", "_").replace("/", "_").replace("\\", "_")
