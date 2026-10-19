"""Freeze paired model predictions for a fresh three-way policy validation."""

import argparse
import hashlib
import json
import os
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from experiments.error_to_context.cloud_client import CloudClient, ENV_KEY
from .memory import build_memory
from .predict import SYSTEM, parse_prediction
from .predict_structured import make_structured_messages
from .select import DATA_ROOT, select_candidates
from .trigger_v5 import choose_action


COHORT = ("supervision", "gpt4free", "paper-qa", "vllm", "agents", "private-gpt")
ARCHIVE_SHA256 = "312b0885a208849ee0225d8fc77f3c6a14df3c7477a67d7a1715d37d1dea239a"
CODE_FILES = ("TRIGGER_V5_PROTOCOL.md", "trigger_v5.py", "explore_static_types.py",
              "trigger_v3.py", "select.py", "memory.py", "predict.py",
              "predict_structured.py", "predict_trigger_v5.py")


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_path(case: dict) -> Path:
    return DATA_ROOT / case["repo"] / "repo_without_types" / case["callee_file"]


def select_v5() -> list[dict]:
    cases = select_candidates(COHORT, limit=10_000)
    if len({case["case_id"] for case in cases}) != len(cases):
        raise ValueError("Duplicate v5 case")
    for case in cases:
        path = _source_path(case)
        if "original_repo" in path.parts:
            raise ValueError("Typed source in selection")
        if (DATA_ROOT / case["repo"] / "original_repo" / case["callee_file"]).exists():
            raise ValueError(f"Typed reference already present: {case['case_id']}")
        case["callee_source_sha256"] = _hash(path.read_bytes())
        case["return_memory"], case["return_memory_hash"] = build_memory(case)
        case["trigger_action"] = choose_action(case)
    return cases


def _load_local_key() -> None:
    if os.environ.get(ENV_KEY):
        return
    dotenv = Path(__file__).resolve().parents[2] / ".env"
    if not dotenv.is_file():
        raise RuntimeError(f"{ENV_KEY} is not set and no local .env file exists")
    for line in dotenv.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.removeprefix("export ").strip() == ENV_KEY:
            os.environ[ENV_KEY] = value.strip().strip('"').strip("'")
            break
    if not os.environ.get(ENV_KEY):
        raise RuntimeError(f"{ENV_KEY} is not set")


def _code_hashes() -> dict:
    parent = Path(__file__).parent
    return {name: _hash((parent / name).read_bytes()) for name in CODE_FILES}


def _verify_selection(cases: list[dict]) -> None:
    for case in cases:
        if _hash(_source_path(case).read_bytes()) != case["callee_source_sha256"]:
            raise ValueError(f"Untyped source changed: {case['case_id']}")
        if case["trigger_action"] != choose_action(case):
            raise ValueError(f"Policy action changed: {case['case_id']}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-api-calls", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if "original_repo" in output.parts:
        raise ValueError("Output cannot be inside typed reference")
    if args.resume:
        if not output.is_dir() or (output / "predictions_frozen.json").exists():
            raise ValueError("Resume requires an unfinished run directory")
        manifest = json.loads((output / "manifest.json").read_text())
        selection_bytes = (output / "selection.json").read_bytes()
        if _hash(selection_bytes) != manifest["selection_sha256"]:
            raise ValueError("Selection changed during run")
        if manifest["code_sha256"] != _code_hashes():
            raise ValueError("Code or protocol changed during run")
        cases = json.loads(selection_bytes)
        _verify_selection(cases)
    else:
        if output.exists():
            raise FileExistsError(output)
        cases = select_v5()
        selection_bytes = json.dumps(cases, indent=2, sort_keys=True).encode()
        manifest = None

    expected = 2 * len(cases)
    if args.max_api_calls < expected:
        raise ValueError(f"Call cap {args.max_api_calls} is below required {expected}")
    if args.dry_run:
        print(json.dumps({"cases": len(cases), "paired_calls": expected,
                          "actions": dict(Counter(c["trigger_action"] for c in cases)),
                          "writes": 0, "api_calls": 0}, indent=2))
        return 0

    _load_local_key()
    client = CloudClient(model="gpt-5.4-mini", max_retries=0)
    if not args.resume:
        output.mkdir(parents=True)
        (output / "selection.json").write_bytes(selection_bytes)
        head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
        manifest = {"phase": "holdout", "study": "three_way_trigger_v5",
                    "created_utc": datetime.now(timezone.utc).isoformat(),
                    "repositories": COHORT, "cases": len(cases),
                    "selection_sha256": _hash(selection_bytes),
                    "code_sha256": _code_hashes(), "git_head": head,
                    "archive_sha256": ARCHIVE_SHA256,
                    "model": client.model, "endpoint_host": urlparse(client.base_url).hostname,
                    "temperature": 0.0, "max_tokens": 1024,
                    "system_prompt_sha256": _hash(SYSTEM.encode())}
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2))

    rows_path = output / "rows.jsonl"
    existing = [json.loads(line) for line in rows_path.read_text().splitlines() if line.strip()] \
        if rows_path.exists() else []
    done = {(row["case_id"], row["arm"]) for row in existing}
    if len(done) != len(existing) or len(existing) > expected:
        raise ValueError("Duplicate or excess existing rows")
    allowed = {(case["case_id"], arm) for case in cases for arm in ("A", "B")}
    if not done <= allowed:
        raise ValueError("Unexpected existing row")
    with rows_path.open("a") as rows_file:
        for number, case in enumerate(cases, start=1):
            for arm in ("A", "B"):
                if (case["case_id"], arm) in done:
                    continue
                messages = make_structured_messages(case, arm)
                response, record = client.chat(messages, temperature=0.0, max_tokens=1024)
                if record.status != "success" or record.input_tokens is None or record.output_tokens is None:
                    raise RuntimeError(f"Cloud call incomplete at case {number} arm {arm}: {record.status}")
                prediction, parse_error = parse_prediction(response)
                row = {"case_id": case["case_id"], "arm": arm,
                       "prediction": prediction, "valid": parse_error is None,
                       "error": parse_error, "prompt_hash": record.prompt_hash,
                       "memory_hash": case["return_memory_hash"] if arm == "B" else None,
                       "response_id": record.response_id, "status": record.status,
                       "input_tokens": record.input_tokens,
                       "output_tokens": record.output_tokens,
                       "latency_ms": record.latency_ms,
                       "raw_response": response[:1000]}
                rows_file.write(json.dumps(row, sort_keys=True) + "\n")
                rows_file.flush()
            if number % 10 == 0 or number == len(cases):
                print(f"{number}/{len(cases)} paired cases", flush=True)
    rows_bytes = rows_path.read_bytes()
    rows = [line for line in rows_bytes.splitlines() if line.strip()]
    if len(rows) != expected:
        raise ValueError(f"Incomplete run: {len(rows)}/{expected} rows")
    (output / "predictions_frozen.json").write_text(json.dumps({
        "rows_sha256": _hash(rows_bytes), "rows": expected,
        "frozen_utc": datetime.now(timezone.utc).isoformat()}, indent=2))
    print(f"Frozen {expected} predictions at {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
