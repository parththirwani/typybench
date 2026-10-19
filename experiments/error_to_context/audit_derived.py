"""Compare mypy errors before and after a frozen model-derived baseline."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from .diagnostics import _ERROR_LINE_RE


TARGETS = {
    "sphinx": "sphinx",
    "gradio": "gradio",
    "openai-python": "src/openai",
    "fastapi": "fastapi",
}
DATA_ROOT = Path("/home/too_geeky/research/typybenchdata")


def _run(root: Path, target: str) -> list[dict]:
    env = os.environ.copy()
    env["MYPY_CACHE_DIR"] = "/tmp/typybench-derived-mypy-cache"
    command = [sys.executable, "-m", "mypy", "--no-incremental",
               "--show-error-codes", "--check-untyped-defs",
               "--ignore-missing-imports", "--explicit-package-bases", target]
    result = subprocess.run(command, cwd=root, env=env, text=True,
                            capture_output=True, timeout=180)
    if result.returncode not in (0, 1):
        raise RuntimeError((result.stderr or result.stdout)[:1000])
    errors = []
    for line in result.stdout.splitlines():
        match = _ERROR_LINE_RE.match(line)
        if not match:
            continue
        path, lineno, message, code = match.groups()
        filepath = Path(path)
        if filepath.is_absolute():
            try:
                filepath = filepath.relative_to(root)
            except ValueError:
                continue
        errors.append({
            "file": filepath.as_posix(), "line": int(lineno),
            "code": code, "message": message.strip(),
        })
    return errors


def audit(repo: str, derived_root: Path) -> dict:
    raw_root = DATA_ROOT / repo / "repo_without_types"
    if not raw_root.is_dir() or not derived_root.is_dir():
        raise FileNotFoundError("Source or derived repository missing")
    target = TARGETS[repo]
    raw = _run(raw_root, target)
    derived = _run(derived_root, target)
    key = lambda e: (e["file"], e["line"], e["code"], e["message"])
    raw_set = {key(e) for e in raw}
    derived_set = {key(e) for e in derived}
    new = [e for e in derived if key(e) not in raw_set]
    lost = [e for e in raw if key(e) not in derived_set]
    return {
        "repo": repo, "target": target,
        "command": [sys.executable, "-m", "mypy", "--no-incremental",
                    "--show-error-codes", "--check-untyped-defs",
                    "--ignore-missing-imports", "--explicit-package-bases", target],
        "raw_count": len(raw), "derived_count": len(derived),
        "new_count": len(new), "lost_count": len(lost),
        "new_by_code": dict(Counter(e["code"] for e in new)),
        "new_errors": new, "lost_errors": lost,
        "raw_source": str(raw_root),
        "derived_source": str(derived_root),
        "derived_manifest_sha256": hashlib.sha256(
            (derived_root / "derived_baseline_manifest.json").read_bytes()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", choices=tuple(TARGETS), required=True)
    parser.add_argument("--derived-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(output)
    result = audit(args.repo, Path(args.derived_root).resolve())
    output.write_text(json.dumps(result, indent=2))
    print(json.dumps({key: value for key, value in result.items()
                      if key not in {"new_errors", "lost_errors"}}, indent=2))
    print("First new errors:")
    for error in result["new_errors"][:8]:
        print(f"  {error['file']}:{error['line']} [{error['code']}] {error['message']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
