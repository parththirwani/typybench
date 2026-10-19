"""Freeze paired cloud predictions without reading the typed reference."""

import argparse
import ast
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from experiments.error_to_context.cloud_client import CloudClient, ENV_KEY
from .select import REPOSITORIES, select_candidates


SYSTEM = (
    "Infer the Python return type of the imported function named in the user message. "
    "Use only the supplied evidence. Answer only JSON in this form: "
    '{"return_type": "Python type expression"}. '
    "Do not include Markdown, imports, explanations, or executable code."
)


def make_messages(case: dict, arm: str) -> list[dict]:
    if arm not in ("A", "B"):
        raise ValueError(arm)
    prompt = (
        f"Repository: {case['repo']}\n"
        f"Target imported function: {case['callee_symbol']} in {case['callee_file']}\n"
        f"Import at caller: {case['import_statement']}\n"
        f"Caller function from {case['source_file']}:\n"
        f"```python\n{case['function_source']}\n```"
    )
    if arm == "B":
        prompt += (
            f"\nRetrieved untyped target definition from {case['callee_file']}:\n"
            f"```python\n{case['callee_content']}\n```"
        )
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]


def parse_prediction(response: str) -> tuple[str | None, str | None]:
    value = response.strip()
    if value.startswith("```json"):
        value = value[7:]
    elif value.startswith("```"):
        value = value[3:]
    if value.endswith("```"):
        value = value[:-3]
    try:
        payload = json.loads(value.strip())
    except json.JSONDecodeError:
        return None, "Output is not JSON"
    if not isinstance(payload, dict) or not isinstance(payload.get("return_type"), str):
        return None, "Missing string return_type"
    prediction = payload["return_type"].strip()
    if not prediction or len(prediction) > 256:
        return None, "Empty or overlong return type"
    try:
        normalized = ast.unparse(ast.parse(prediction, mode="eval").body)
    except SyntaxError:
        return None, "Return type is not a Python expression"
    return normalized, None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("smoke", "holdout"), required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-api-calls", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cases = select_candidates()
    selected = cases[:6] if args.phase == "smoke" else cases[6:]
    required_calls = 2 * len(selected)
    if args.max_api_calls < required_calls:
        raise ValueError(f"Cap {args.max_api_calls} is below the {required_calls} paired calls required")
    output = Path(args.output_dir).resolve()
    if output.exists():
        raise FileExistsError(output)
    if "original_repo" in output.parts:
        raise ValueError("Output cannot be inside the typed reference")
    if args.dry_run:
        print(f"{args.phase}: {len(selected)} cases, {required_calls} logical calls, zero calls in dry-run")
        return 0
    if not os.environ.get(ENV_KEY):
        raise RuntimeError(f"{ENV_KEY} is not set")

    output.mkdir(parents=True)
    selection_bytes = json.dumps(selected, indent=2, sort_keys=True).encode()
    (output / "selection.json").write_bytes(selection_bytes)
    client = CloudClient(max_retries=0)
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()
    manifest = {
        "phase": args.phase,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "repositories": REPOSITORIES,
        "cases": len(selected),
        "selection_sha256": _sha256(selection_bytes),
        "git_head": head,
        "model": client.model,
        "endpoint_host": urlparse(client.base_url).hostname,
        "temperature": 0.0,
        "max_tokens": 1024,
        "system_prompt_sha256": _sha256(SYSTEM.encode()),
        "predict_code_sha256": _sha256(Path(__file__).read_bytes()),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2))

    rows_path = output / "rows.jsonl"
    with rows_path.open("w") as rows_file:
        for number, case in enumerate(selected, start=1):
            for arm in ("A", "B"):
                messages = make_messages(case, arm)
                response, record = client.chat(messages, temperature=0.0, max_tokens=1024)
                prediction, parse_error = parse_prediction(response)
                row = {
                    "case_id": case["case_id"], "arm": arm,
                    "prediction": prediction,
                    "valid": record.status == "success" and parse_error is None,
                    "error": parse_error or record.error,
                    "prompt_hash": record.prompt_hash,
                    "callee_hash": case["callee_hash"] if arm == "B" else None,
                    "response_id": record.response_id,
                    "status": record.status,
                    "input_tokens": record.input_tokens,
                    "output_tokens": record.output_tokens,
                    "latency_ms": record.latency_ms,
                    "raw_response": response[:1000],
                }
                rows_file.write(json.dumps(row, sort_keys=True) + "\n")
                rows_file.flush()
            print(f"{number}/{len(selected)} {case['case_id']}", flush=True)

    rows_bytes = rows_path.read_bytes()
    (output / "predictions_frozen.json").write_text(json.dumps({
        "rows_sha256": _sha256(rows_bytes),
        "rows": required_calls,
        "frozen_utc": datetime.now(timezone.utc).isoformat(),
    }, indent=2))
    print(f"Frozen {required_calls} predictions at {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
