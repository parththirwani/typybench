import os
import sys
import subprocess
from pathlib import Path
from .cloud_client import ENV_KEY, DEFAULT_BASE_URL, DEFAULT_MODEL


DATA_PATH = "/home/too_geeky/research/typybenchdata"


def check_data_path(repo: str = "flask"):
    if not os.path.isdir(DATA_PATH):
        return False, f"Data path not found: {DATA_PATH}"
    repo_dir = os.path.join(DATA_PATH, repo)
    if not os.path.isdir(repo_dir):
        return False, f"{repo} directory not found in data path"
    if not os.path.isdir(os.path.join(repo_dir, "repo_without_types")):
        return False, f"repo_without_types not found in {repo}"
    return True, None


def check_split(repo: str = "flask"):
    import json
    split_path = os.path.join(DATA_PATH, "split.json")
    if not os.path.isfile(split_path):
        return False, f"split.json not found"
    with open(split_path) as f:
        split = json.load(f)
    if repo not in split.get("dev", []):
        return False, f"{repo} not in dev split"
    return True, None


def check_venv():
    venv_python = Path(sys.prefix) / "bin" / "python"
    if not venv_python.exists():
        return False, f"Virtual env python not found at {venv_python}"
    return True, None


def check_mypy_version():
    try:
        result = subprocess.run(
            [sys.executable, "-m", "mypy", "--version"],
            capture_output=True, text=True, timeout=30,
        )
        ver = result.stdout.strip()
        if "1.11.1" not in ver:
            return False, f"Unexpected mypy version: {ver}"
        return True, ver
    except Exception as e:
        return False, str(e)


def check_api_key():
    key = os.environ.get(ENV_KEY)
    if key is None:
        return False, f"{ENV_KEY} not set"
    if len(key) < 8:
        return False, f"{ENV_KEY} appears too short"
    return True, None


def check_output_path(path: str):
    abs_path = os.path.abspath(path)
    if "original_repo" in Path(abs_path).parts:
        return False, "Output path must not be inside original_repo"
    return True, None


def run_preflight(output_path: str = None, dry_run: bool = False, repo: str = "flask"):
    results = {}
    ok, msg = check_data_path(repo)
    results["data_path"] = (ok, msg if not ok else "ok")
    ok, msg = check_split(repo)
    results["dev_split"] = (ok, msg if not ok else "ok")
    ok, msg = check_venv()
    results["venv"] = (ok, msg if not ok else "ok")
    ok, msg = check_mypy_version()
    results["mypy_version"] = (ok, msg if not ok else f"ok: {msg}")
    if dry_run:
        results["api_key"] = (True, "not required for dry-run")
    else:
        ok, msg = check_api_key()
        results["api_key"] = (ok, msg if not ok else "set")
    if output_path:
        ok, msg = check_output_path(output_path)
        results["output_path"] = (ok, msg if not ok else "ok")

    all_ok = all(ok for ok, _ in results.values())
    return all_ok, results
