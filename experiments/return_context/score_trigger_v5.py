"""Score the frozen v5 three-way policy after reference extraction."""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from .analyze_v5_development import analyze
from .predict_trigger_v5 import _code_hashes, _hash
from .score import score
from .trigger_v5 import choose_action


def score_v5(run_dir: Path, *, chooser=choose_action,
             code_hashes=_code_hashes, study="three_way_trigger_v5",
             min_evaluable=90, min_saving_pct=15.0) -> dict:
    manifest = json.loads((run_dir / "manifest.json").read_text())
    frozen = json.loads((run_dir / "predictions_frozen.json").read_text())
    extraction = json.loads((run_dir / "extraction_manifest.json").read_text())
    if manifest["study"] != study:
        raise ValueError("Wrong study")
    actual_hashes = code_hashes()
    if study == "three_way_trigger_v5" and actual_hashes.get("select.py") != manifest["code_sha256"].get("select.py"):
        snapshot = Path(__file__).parent / "frozen_v5_select.py"
        actual_hashes["select.py"] = _hash(snapshot.read_bytes())
    if manifest["code_sha256"] != actual_hashes:
        raise ValueError("Code or protocol changed after prediction")
    if extraction["archive_sha256"] != manifest["archive_sha256"]:
        raise ValueError("Reference archive differs from source archive")
    selection_bytes = (run_dir / "selection.json").read_bytes()
    rows_bytes = (run_dir / "rows.jsonl").read_bytes()
    if (_hash(selection_bytes) != manifest["selection_sha256"] or
            _hash(rows_bytes) != frozen["rows_sha256"]):
        raise ValueError("Frozen artifacts changed")
    cases = json.loads(selection_bytes)
    for case in cases:
        if case["trigger_action"] != chooser(case):
            raise ValueError(f"Policy action changed: {case['case_id']}")

    paired = score(run_dir)
    summary = analyze(run_dir, chooser=chooser)
    if summary["missing_usage"] or paired["usage"]["B"]["missing_usage_rows"]:
        raise ValueError("Incomplete cloud token accounting")
    scored = {case["case_id"]: case for case in paired["cases"]}
    by_repo = defaultdict(Counter)
    missing_reasons = Counter()
    static_errors = []
    for case in cases:
        result = scored[case["case_id"]]
        repo = case["repo"]
        by_repo[repo]["selected"] += 1
        if not result["evaluable"]:
            missing_reasons[result["reason"]] += 1
            continue
        by_repo[repo]["evaluable"] += 1
        by_repo[repo]["a_exact"] += result["a_correct"]
        by_repo[repo]["b_exact"] += result["b_correct"]
        action = chooser(case)
        if action.startswith("static:"):
            by_repo[repo]["static_evaluable"] += 1
            correct = action.removeprefix("static:") == result["reference"]
            by_repo[repo]["static_correct"] += correct
            if not correct:
                static_errors.append({"case_id": case["case_id"], "prediction":
                                      action.removeprefix("static:"),
                                      "reference": result["reference"]})
        else:
            correct = result["a_correct" if action == "A" else "b_correct"]
        by_repo[repo]["policy_exact"] += correct

    summary["missing_reference_reasons"] = dict(missing_reasons)
    summary["by_repo"] = {repo: dict(counts) for repo, counts in by_repo.items()}
    summary["static_errors"] = static_errors
    summary["substantial_saving_gate"] = (
        summary["evaluable"] >= min_evaluable and
        summary["hybrid_exact"] > summary["a_exact"] and
        summary["versus_a_p"] < 0.05 and
        summary["input_savings_pct"] >= min_saving_pct)
    summary["within_three_of_always_memory"] = (
        summary["hybrid_exact"] >= summary["b_exact"] - 3)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    output = run_dir / "v5_scores.json"
    if output.exists():
        raise FileExistsError(output)
    result = score_v5(run_dir)
    output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
