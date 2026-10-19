"""Run isolated A/B annotation repairs on frozen derived-baseline sites."""

import argparse
import dataclasses
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .cloud_client import CloudClient, ENV_KEY
from .audit_saved_pair import audit as audit_saved_pair
from .correction import _run_and_parse_all, run_correction
from .diagnostics import Case, Diagnostic
from .retrieval import RetrievedDef
from .select_derived_sites import _source_hash
from .summarize import summarize


TARGETS = {"sphinx": "sphinx", "gradio": "gradio"}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load(repo: str, selected_path: Path) -> tuple[Path, list[dict], str]:
    selected_bytes = selected_path.read_bytes()
    selected = json.loads(selected_bytes)
    if selected["repo"] != repo:
        raise ValueError("Selection repository mismatch")
    baseline = Path(selected["baseline"])
    if _source_hash(baseline) != selected["baseline_source_sha256"]:
        raise ValueError("Baseline changed since site selection")
    return baseline, selected["eligible"], _sha256(selected_bytes)


def _case(data: dict) -> Case:
    diag = data["diagnostic"]
    return Case(
        case_id=data["case_id"],
        diagnostic=Diagnostic(file=diag["file"], line=diag["line"],
                              column=diag["column"], code=diag["code"],
                              message=diag["message"]),
        source_line=data["source_line"],
        window_before=data["window_before"],
        window_after=data["window_after"],
        symbol_name=data["symbol_name"],
        resolved_def_path=None, resolved_def_span=None,
        edit_file=data["edit_file"], edit_line=data["edit_line"],
        edit_window_before=data["edit_window_before"],
        edit_source_line=data["edit_source_line"],
        edit_window_after=data["edit_window_after"],
        repair_parameter=data["parameter"],
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sphinx-selection", required=True)
    parser.add_argument("--gradio-selection", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-api-calls", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    configs = {
        "sphinx": Path(args.sphinx_selection),
        "gradio": Path(args.gradio_selection),
    }
    loaded = {repo: _load(repo, path) for repo, path in configs.items()}
    case_count = sum(len(data[1]) for data in loaded.values())
    if args.max_api_calls < 2 * case_count:
        raise ValueError(f"Cap {args.max_api_calls} is below {2 * case_count} paired calls")
    output = Path(args.output_dir).resolve()
    if output.exists() or "original_repo" in output.parts:
        raise ValueError("Output exists or enters typed reference")
    if args.dry_run:
        print(f"{case_count} sites, {2 * case_count} calls, zero in dry-run")
        return 0
    if not os.environ.get(ENV_KEY):
        raise RuntimeError(f"{ENV_KEY} missing")
    output.mkdir(parents=True)
    client = CloudClient(max_retries=0)
    (output / "manifest.json").write_text(json.dumps({
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "model": client.model,
        "endpoint_host": urlparse(client.base_url).hostname,
        "selection_sha256": {repo: data[2] for repo, data in loaded.items()},
        "baseline_source_sha256": {repo: _source_hash(data[0])
                                   for repo, data in loaded.items()},
        "cases": case_count,
        "max_api_calls": args.max_api_calls,
        "mypy_targets": TARGETS,
        "same_system_prompt_both_arms": True,
    }, indent=2))

    for repo in ("sphinx", "gradio"):
        baseline, cases, _ = loaded[repo]
        baseline_errors = _run_and_parse_all(str(baseline), TARGETS[repo])
        for index, data in enumerate(cases, start=1):
            case = _case(data)
            retrieved = RetrievedDef(**data["retrieved"])
            for arm, definition in (("A", None), ("B", retrieved)):
                if len(client.records) >= args.max_api_calls:
                    raise RuntimeError("API call cap reached before completing pairs")
                row = run_correction(case, str(baseline), str(output), client,
                                     retrieved_def=definition,
                                     mypy_target=TARGETS[repo],
                                     baseline_errors=baseline_errors)
                safe_id = case.case_id.replace(":", "_").replace("/", "_")
                row_path = output / "corrections" / f"{safe_id}_{arm}" / "row.json"
                row_path.write_text(json.dumps(dataclasses.asdict(row), indent=2))
            print(f"{repo} {index}/{len(cases)} {case.case_id}", flush=True)

    result = summarize(str(output))
    (output / "summary.json").write_text(json.dumps(result, indent=2))
    strict = audit_saved_pair(output, list(configs.values()))
    (output / "audited_summary.json").write_text(json.dumps(strict, indent=2))
    print(json.dumps({key: value for key, value in strict.items() if key != "rows"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
