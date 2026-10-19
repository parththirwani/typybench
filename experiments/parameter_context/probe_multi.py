"""Exploratory multi-call-memory probe on the already scored development cohort."""

import argparse
import hashlib
import json
import os
from pathlib import Path

from experiments.error_to_context.cloud_client import CloudClient, ENV_KEY
from .multi_select import select_multi_cases
from .predict import SYSTEM, parse_prediction


DEVELOPMENT_REPOS = (
    "fastapi", "openai-python", "urllib3", "sphinx", "gradio", "haystack",
)


def make_message(case: dict) -> list[dict]:
    prompt = (
        f"Repository: {case['repo']}\n"
        f"Target: parameter {case['parameter']} of {case['callee_symbol']} "
        f"in {case['callee_file']}\n"
        f"Untyped target function:\n```python\n{case['callee_block']}\n```"
        f"\nIndexed cross-file calls supplying {case['parameter']}:\n"
        f"{case['memory']}"
    )
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous-run", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-api-calls", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    previous = Path(args.previous_run)
    old_cases = {case["case_id"]: case for case in json.loads(
        (previous / "selection.json").read_text())}
    candidates = select_multi_cases(repositories=DEVELOPMENT_REPOS, limit=10000)
    selected = [case for case in candidates if case["case_id"] in old_cases]
    for case in selected:
        if case["callee_block"] != old_cases[case["case_id"]]["callee_block"]:
            raise ValueError(f"Target function changed: {case['case_id']}")
    if args.max_api_calls < len(selected):
        raise ValueError(f"Cap {args.max_api_calls} is below {len(selected)} calls")
    output = Path(args.output_dir).resolve()
    if output.exists():
        raise FileExistsError(output)
    if args.dry_run:
        print(f"{len(selected)} development cases, {len(selected)} calls, zero in dry-run")
        return 0
    if not os.environ.get(ENV_KEY):
        raise RuntimeError(f"{ENV_KEY} missing")
    output.mkdir(parents=True)
    selection = json.dumps(selected, indent=2, sort_keys=True).encode()
    (output / "selection.json").write_bytes(selection)
    client = CloudClient(max_retries=0)
    rows_path = output / "rows.jsonl"
    with rows_path.open("w") as rows_file:
        for index, case in enumerate(selected, start=1):
            response, record = client.chat(make_message(case), temperature=0.0, max_tokens=1024)
            prediction, parse_error = parse_prediction(response)
            row = {
                "case_id": case["case_id"],
                "prediction": prediction,
                "valid": record.status == "success" and parse_error is None,
                "error": parse_error or record.error,
                "prompt_hash": record.prompt_hash,
                "response_id": record.response_id,
                "input_tokens": record.input_tokens,
                "output_tokens": record.output_tokens,
                "latency_ms": record.latency_ms,
                "raw_response": response[:1000],
            }
            rows_file.write(json.dumps(row, sort_keys=True) + "\n")
            rows_file.flush()
            print(f"{index}/{len(selected)} {case['case_id']}", flush=True)
    (output / "predictions_frozen.json").write_text(json.dumps({
        "selection_sha256": hashlib.sha256(selection).hexdigest(),
        "rows_sha256": hashlib.sha256(rows_path.read_bytes()).hexdigest(),
        "rows": len(selected),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
