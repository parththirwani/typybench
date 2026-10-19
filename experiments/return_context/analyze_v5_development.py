"""Exploratory cost and accuracy analysis on previously scored paired runs."""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from .score import _mcnemar_two_sided, score
from .trigger_v5 import choose_action


def analyze(run_dir: Path, *, chooser=choose_action) -> dict:
    paired = score(run_dir)
    cases = json.loads((run_dir / "selection.json").read_text())
    rows = [json.loads(line) for line in (run_dir / "rows.jsonl").read_text().splitlines()
            if line.strip()]
    row_by_case = defaultdict(dict)
    for row in rows:
        row_by_case[row["case_id"]][row["arm"]] = row
    scored = {case["case_id"]: case for case in paired["cases"]}

    actions = Counter()
    static_evaluable = static_correct = hybrid_correct = input_tokens = output_tokens = 0
    versus_a = Counter()
    versus_b = Counter()
    missing_usage = 0
    for case in cases:
        action = chooser(case)
        actions[action] += 1
        scored_case = scored[case["case_id"]]
        if not action.startswith("static:"):
            row = row_by_case[case["case_id"]][action]
            input_tokens += row["input_tokens"] or 0
            output_tokens += row["output_tokens"] or 0
            missing_usage += row["input_tokens"] is None
        if not scored_case["evaluable"]:
            continue
        if action.startswith("static:"):
            static_evaluable += 1
            success = scored_case["reference"] == action.removeprefix("static:")
            static_correct += success
        else:
            success = scored_case["a_correct" if action == "A" else "b_correct"]
        hybrid_correct += success
        a_ok = scored_case["a_correct"]
        b_ok = scored_case["b_correct"]
        versus_a["both" if a_ok and success else
                 "a_only" if a_ok else
                 "hybrid_only" if success else "neither"] += 1
        versus_b["both" if b_ok and success else
                 "b_only" if b_ok else
                 "hybrid_only" if success else "neither"] += 1

    b_input = paired["usage"]["B"]["input_tokens"]
    b_total = b_input + paired["usage"]["B"]["output_tokens"]
    return {
        "run": run_dir.name,
        "selected": paired["selected"],
        "evaluable": paired["evaluable"],
        "actions": dict(actions),
        "static_evaluable": static_evaluable,
        "static_correct": static_correct,
        "a_exact": paired["a_exact"],
        "b_exact": paired["b_exact"],
        "hybrid_exact": hybrid_correct,
        "versus_a": dict(versus_a),
        "versus_a_p": _mcnemar_two_sided(versus_a["a_only"], versus_a["hybrid_only"]),
        "versus_b": dict(versus_b),
        "versus_b_p": _mcnemar_two_sided(versus_b["b_only"], versus_b["hybrid_only"]),
        "hybrid_input_tokens": input_tokens,
        "hybrid_output_tokens": output_tokens,
        "b_input_tokens": b_input,
        "b_output_tokens": paired["usage"]["B"]["output_tokens"],
        "input_savings_pct": 100 * (b_input - input_tokens) / b_input,
        "total_savings_pct": 100 * (b_total - input_tokens - output_tokens) / b_total,
        "missing_usage": missing_usage,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dirs", nargs="+", type=Path)
    parser.add_argument("--policy", choices=("v5", "v6"), default="v5")
    args = parser.parse_args()
    if args.policy == "v6":
        from .trigger_v6 import choose_action as selected_chooser
    else:
        selected_chooser = choose_action
    for run_dir in args.run_dirs:
        print(json.dumps(analyze(run_dir, chooser=selected_chooser), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
