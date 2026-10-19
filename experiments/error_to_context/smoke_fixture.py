"""Tiny 2-file fixture for the smoke test — A-only (local error) validation.

All errors are local [assignment] mismatches requiring no cross-file retrieval.
Arm B is never triggered because _extract_callee returns None for assignment codes.
Every case tests the error-only (A) arm.

Pre-annotated wrong types persist through baseline generation because the model
preserves existing annotations and only adds missing ones.

Case 1 (app.py:line): `x: int = "hello"` — local var type mismatch [assignment]
  Fix: change `x: int` to `x: str`

Case 2 (app.py:line): `count: str = len(items)` — return type mismatch [assignment]
  Fix: change `count: str` to `count: int`
"""
import os
import tempfile


FILES_WITHOUT_TYPES = {
    "src/mylib/__init__.py": "",
    "src/app.py": """
from __future__ import annotations

def run(items: list[str]) -> None:
    x: int = "hello"
    count: str = len(items)
""",
}


def create_smoke_repo_without_types(dest=None):
    if dest is None:
        dest = tempfile.mkdtemp(suffix="_smoke_without_types")
    for relpath, content in FILES_WITHOUT_TYPES.items():
        abspath = os.path.join(dest, relpath)
        os.makedirs(os.path.dirname(abspath), exist_ok=True)
        with open(abspath, "w") as f:
            f.write(content)
    return dest