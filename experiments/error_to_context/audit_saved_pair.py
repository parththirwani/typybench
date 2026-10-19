"""Re-score saved repair rows after checking the target annotation itself."""

import argparse
import ast
import json
from pathlib import Path

from .correction import _parameter_annotation
from .summarize import load_results


def audit(run_dir: Path, selections: list[Path]) -> dict:
    cases = {}
    for path in selections:
        data = json.loads(path.read_text())
        for case in data["eligible"]:
            cases[case["case_id"]] = {
                **case,
                "baseline": Path(data["baseline"]),
            }
    saved = load_results(str(run_dir))
    if set(saved) != set(cases):
        raise ValueError("Saved rows and frozen selection do not match")
    details = []
    both = a_only = b_only = neither = 0
    for case_id, arms in sorted(saved.items()):
        if set(arms) != {"A", "B"}:
            raise ValueError(f"Missing arm for {case_id}")
        case = cases[case_id]
        baseline_path = case["baseline"] / case["edit_file"]
        baseline_tree = ast.parse(baseline_path.read_text())
        old_annotation = _parameter_annotation(
            baseline_tree, case["symbol_name"], case["parameter"])
        outcomes = {}
        for arm, row in arms.items():
            reason = None
            success = bool(row.clean_correction)
            if success:
                safe_id = case_id.replace(":", "_").replace("/", "_")
                corrected_path = (run_dir / "corrections" / f"{safe_id}_{arm}"
                                  / case["edit_file"])
                corrected = ast.parse(corrected_path.read_text())
                updated_annotation = _parameter_annotation(
                    corrected, case["symbol_name"], case["parameter"])
                if updated_annotation is None:
                    success = False
                    reason = "Target annotation removed"
                elif (old_annotation is not None
                      and ast.dump(old_annotation) == ast.dump(updated_annotation)):
                    success = False
                    reason = "Target annotation unchanged"
            outcomes[arm] = success
            details.append({
                "case_id": case_id, "arm": arm,
                "saved_clean": row.clean_correction,
                "audited_clean": success, "reason": reason,
                "input_tokens": row.usage_input_tokens,
                "output_tokens": row.usage_output_tokens,
            })
        a, b = outcomes["A"], outcomes["B"]
        if a and b:
            both += 1
        elif a:
            a_only += 1
        elif b:
            b_only += 1
        else:
            neither += 1
    return {
        "total_cases": len(cases), "both": both, "a_only": a_only,
        "b_only": b_only, "neither": neither,
        "a_clean": both + a_only, "b_clean": both + b_only,
        "rows": details,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--selection", action="append", required=True)
    args = parser.parse_args()
    run_dir = Path(args.run_dir)
    output = run_dir / "audited_summary.json"
    if output.exists():
        raise FileExistsError(output)
    result = audit(run_dir, [Path(path) for path in args.selection])
    output.write_text(json.dumps(result, indent=2))
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}, indent=2))
    for row in result["rows"]:
        if row["saved_clean"] != row["audited_clean"]:
            print(f"Corrected {row['case_id']} {row['arm']}: {row['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
