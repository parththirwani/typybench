import os
import re
import hashlib
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional


TARGET_CODES = {"arg-type", "assignment", "attr-defined"}

_ERROR_LINE_RE = re.compile(
    r"^(.+?):(\d+):(?:\d+:)?\s*error:\s*(.+?)\s+\[([a-z][a-z0-9-]*)\]\s*$"
)


@dataclass(frozen=True)
class Diagnostic:
    file: str
    line: int
    column: int
    code: str
    message: str

    def case_id(self) -> str:
        normalized = re.sub(r"\s+", " ", self.message.strip())
        message_hash = hashlib.sha256(normalized.encode()).hexdigest()[:8]
        return f"{self.file}:{self.line}:{self.column}:{self.code}:{message_hash}"


@dataclass(frozen=True)
class Case:
    case_id: str
    diagnostic: Diagnostic
    source_line: str
    window_before: str
    window_after: str
    symbol_name: Optional[str]
    resolved_def_path: Optional[str]
    resolved_def_span: Optional[tuple[int, int]]
    excluded_reason: Optional[str] = None
    edit_file: Optional[str] = None
    edit_line: Optional[int] = None
    edit_window_before: str = ""
    edit_source_line: str = ""
    edit_window_after: str = ""
    repair_parameter: Optional[str] = None


def run_mypy(repo_path: str, timeout: int = 120,
             target_rel: Optional[str] = None) -> list[str]:
    source_root = os.path.join(repo_path, "src")
    if os.path.isdir(os.path.join(source_root, "flask")):
        target = os.path.join(source_root, "flask")
    elif os.path.isdir(os.path.join(repo_path, "typer")):
        target = os.path.join(repo_path, "typer")
    elif os.path.isdir(os.path.join(repo_path, "pre_commit")):
        target = os.path.join(repo_path, "pre_commit")
    elif os.path.isdir(source_root):
        target = source_root
    else:
        target = repo_path
    if target_rel is not None:
        target_path = os.path.normpath(target_rel)
        if (os.path.isabs(target_path) or target_path.startswith("..")
                or not os.path.isdir(os.path.join(repo_path, target_path))):
            raise ValueError(f"Invalid mypy target inside repository: {target_rel}")
        target = target_path
    command = [sys.executable, "-m", "mypy", "--no-incremental", "--show-error-codes",
               "--check-untyped-defs", "--ignore-missing-imports"]
    if target_rel is not None:
        command.append("--explicit-package-bases")
    command.append(target)
    result = subprocess.run(
        command,
        capture_output=True, text=True, timeout=timeout,
        cwd=repo_path,
    )
    if result.returncode not in (0, 1):
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"mypy failed before producing usable diagnostics: {detail[:1000]}")
    stderr_lines = (result.stderr or "").strip().split("\n") if result.stderr else []
    stdout_lines = (result.stdout or "").strip().split("\n") if result.stdout else []
    combined = stdout_lines + stderr_lines
    return [l for l in combined if l.strip()]


def parse_mypy_lines(lines: list[str]) -> list[Diagnostic]:
    diags = []
    for line in lines:
        m = _ERROR_LINE_RE.match(line)
        if not m:
            continue
        filepath, line_str, message, code = m.groups()
        if code not in TARGET_CODES:
            continue
        try:
            line_no = int(line_str)
        except ValueError:
            continue
        col = _extract_column(line)
        diags.append(Diagnostic(
            file=os.path.normpath(filepath),
            line=line_no,
            column=col,
            code=code,
            message=message.strip(),
        ))
    return diags


def _extract_column(error_line: str) -> int:
    parts = error_line.split(":")
    if len(parts) >= 3:
        try:
            return int(parts[2].split()[0])
        except (ValueError, IndexError):
            pass
    return 0


def deduplicate_diagnostics(diags: list[Diagnostic]) -> list[Diagnostic]:
    seen = set()
    result = []
    for d in diags:
        key = d.case_id()
        if key not in seen:
            seen.add(key)
            result.append(d)
    return result


def sort_diagnostics(diags: list[Diagnostic]) -> list[Diagnostic]:
    return sorted(diags, key=lambda d: (d.file, d.line, d.column, d.code))


def read_source_window(filepath: str, line_no: int, context_lines: int = 3, repo_root: str = "") -> tuple[str, str, str]:
    if not os.path.isabs(filepath) and repo_root:
        filepath = os.path.join(repo_root, filepath)
    with open(filepath) as f:
        lines = f.readlines()
    idx = line_no - 1
    start = max(0, idx - context_lines)
    end = min(len(lines), idx + context_lines + 1)
    before = "".join(lines[start:idx])
    affected = lines[idx] if idx < len(lines) else ""
    after = "".join(lines[idx + 1:end])
    return before, affected, after
