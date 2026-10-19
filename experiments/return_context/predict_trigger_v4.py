"""Run unchanged source-signal trigger on eight new TypyBench repositories."""

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from experiments.error_to_context.cloud_client import CloudClient, ENV_KEY
from .memory import build_memory
from .predict import SYSTEM, parse_prediction
from .predict_structured import make_structured_messages
from .select import select_candidates
from .trigger_v3 import choose_arm


COHORT = ("poetry", "rich", "flake8", "nicegui", "pandas-ai",
          "deepface", "gptme", "appworld")


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def select_v4() -> list[dict]:
    cases = select_candidates(COHORT, limit=10_000)
    if len({case["case_id"] for case in cases}) != len(cases):
        raise ValueError("Duplicate v4 case")
    for case in cases:
        case["return_memory"], case["return_memory_hash"] = build_memory(case)
        case["trigger_arm"] = choose_arm(case)
    return cases


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-api-calls", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    cases = select_v4()
    expected = 2 * len(cases)
    if args.max_api_calls < expected:
        raise ValueError(f"Call cap {args.max_api_calls} is below required {expected}")
    output = Path(args.output_dir).resolve()
    if output.exists():
        raise FileExistsError(output)
    if "original_repo" in output.parts:
        raise ValueError("Output cannot be inside typed reference")
    if args.dry_run:
        print(f"{len(cases)} new-repository cases, {expected} paired calls, "
              f"trigger B on {sum(c['trigger_arm'] == 'B' for c in cases)}; "
              "no writes or calls")
        return 0
    if not os.environ.get(ENV_KEY):
        raise RuntimeError(f"{ENV_KEY} is not set")

    output.mkdir(parents=True)
    selection = json.dumps(cases, indent=2, sort_keys=True).encode()
    (output / "selection.json").write_bytes(selection)
    client = CloudClient(max_retries=0)
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                          text=True, check=True).stdout.strip()
    manifest = {
        "phase": "holdout", "study": "source_signal_trigger_v4_new_repositories",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "repositories": COHORT, "cases": len(cases),
        "selection_sha256": _hash(selection),
        "protocol_sha256": _hash((Path(__file__).parent / "TRIGGER_V4_PROTOCOL.md").read_bytes()),
        "trigger_code_sha256": _hash((Path(__file__).parent / "trigger_v3.py").read_bytes()),
        "git_head": head, "model": client.model,
        "endpoint_host": urlparse(client.base_url).hostname,
        "temperature": 0.0, "max_tokens": 1024,
        "system_prompt_sha256": _hash(SYSTEM.encode()),
        "predict_code_sha256": _hash(Path(__file__).read_bytes()),
        "memory_code_sha256": _hash((Path(__file__).parent / "memory.py").read_bytes()),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2))
    rows_path = output / "rows.jsonl"
    with rows_path.open("w") as rows_file:
        for number, case in enumerate(cases, start=1):
            for arm in ("A", "B"):
                messages = make_structured_messages(case, arm)
                response, record = client.chat(messages, temperature=0.0, max_tokens=1024)
                if record.status != "success":
                    raise RuntimeError(
                        f"Cloud call failed for {case['case_id']} arm {arm} "
                        f"with status {record.status}; no freeze written"
                    )
                prediction, parse_error = parse_prediction(response)
                row = {
                    "case_id": case["case_id"], "arm": arm,
                    "prediction": prediction, "valid": parse_error is None,
                    "error": parse_error, "prompt_hash": record.prompt_hash,
                    "memory_hash": case["return_memory_hash"] if arm == "B" else None,
                    "response_id": record.response_id, "status": record.status,
                    "input_tokens": record.input_tokens,
                    "output_tokens": record.output_tokens,
                    "latency_ms": record.latency_ms,
                    "raw_response": response[:1000],
                }
                rows_file.write(json.dumps(row, sort_keys=True) + "\n")
                rows_file.flush()
            print(f"{number}/{len(cases)} {case['case_id']}", flush=True)
    frozen = {"rows_sha256": _hash(rows_path.read_bytes()), "rows": expected,
              "frozen_utc": datetime.now(timezone.utc).isoformat()}
    (output / "predictions_frozen.json").write_text(json.dumps(frozen, indent=2))
    print(f"Frozen {expected} predictions at {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
