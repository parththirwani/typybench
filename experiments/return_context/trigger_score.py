"""Apply the frozen source-signal trigger to paired, reference-scored rows."""

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from .score import _mcnemar_two_sided, score


def choose_arm(case: dict) -> str:
    memory = case["return_memory"]
    return "B" if "assignment line" in memory or "yield line" in memory else "A"


def score_trigger(run_dir: Path, *, chooser=choose_arm,
                  min_trigger_rate: float = 0.1, max_trigger_rate: float = 0.9,
                  require_at_least_b: bool = True, min_evaluable: int = 80,
                  require_significant: bool = False) -> dict:
    # score() validates the selection and response hashes before reading truth.
    paired = score(run_dir)
    cases = json.loads((run_dir / "selection.json").read_text())
    rows = [json.loads(line) for line in (run_dir / "rows.jsonl").read_text().splitlines()
            if line.strip()]
    by_case = defaultdict(dict)
    for row in rows:
        by_case[row["case_id"]][row["arm"]] = row
    scored = {case["case_id"]: case for case in paired["cases"]}
    counts = {"both": 0, "a_only": 0, "trigger_only": 0, "neither": 0}
    vs_b = {"both": 0, "b_only": 0, "trigger_only": 0, "neither": 0}
    chosen_usage = {"input_tokens": 0, "output_tokens": 0, "latency_ms": 0.0,
                    "missing_usage_rows": 0}
    chosen_b_all = chosen_b_evaluable = trigger_correct = 0
    chosen_cases = []
    for case in cases:
        arm = chooser(case)
        chosen_b_all += arm == "B"
        row = by_case[case["case_id"]][arm]
        for key in ("input_tokens", "output_tokens", "latency_ms"):
            chosen_usage[key] += row[key] or 0
        chosen_usage["missing_usage_rows"] += row["input_tokens"] is None
        scored_case = scored[case["case_id"]]
        if not scored_case["evaluable"]:
            continue
        chosen_b_evaluable += arm == "B"
        a_ok = scored_case["a_correct"]
        b_ok = scored_case["b_correct"]
        chosen_ok = b_ok if arm == "B" else a_ok
        trigger_correct += chosen_ok
        counts["both" if a_ok and chosen_ok else
               "a_only" if a_ok else
               "trigger_only" if chosen_ok else "neither"] += 1
        vs_b["both" if b_ok and chosen_ok else
             "b_only" if b_ok else
             "trigger_only" if chosen_ok else "neither"] += 1
        chosen_cases.append({"case_id": case["case_id"], "arm": arm,
                             "trigger_correct": chosen_ok, "a_correct": a_ok,
                             "b_correct": b_ok})
    evaluable = paired["evaluable"]
    b_tokens = paired["usage"]["B"]["input_tokens"]
    savings = (b_tokens - chosen_usage["input_tokens"]) / b_tokens if b_tokens else None
    positive_pilot = (
        evaluable >= min_evaluable
        and evaluable * min_trigger_rate <= chosen_b_evaluable <= evaluable * max_trigger_rate
        and trigger_correct > paired["a_exact"]
        and (not require_at_least_b or trigger_correct >= paired["b_exact"])
        and savings is not None and savings >= 0.05
        and (not require_significant or
             _mcnemar_two_sided(counts["a_only"], counts["trigger_only"]) < 0.05)
        and chosen_usage["missing_usage_rows"] == 0
        and paired["usage"]["B"]["missing_usage_rows"] == 0
    )
    return {
        "selected": paired["selected"], "evaluable": evaluable,
        "missing_reference": paired["missing_reference"],
        "a_exact": paired["a_exact"], "b_exact": paired["b_exact"],
        "trigger_exact": trigger_correct,
        "trigger_b_selected": chosen_b_all,
        "trigger_b_evaluable": chosen_b_evaluable,
        "trigger_rate_evaluable": chosen_b_evaluable / evaluable if evaluable else None,
        "trigger_vs_a": counts,
        "trigger_vs_a_mcnemar_p_two_sided": _mcnemar_two_sided(
            counts["a_only"], counts["trigger_only"]),
        "trigger_vs_b": vs_b,
        "trigger_vs_b_mcnemar_p_two_sided": _mcnemar_two_sided(
            vs_b["b_only"], vs_b["trigger_only"]),
        "usage": {"A": paired["usage"]["A"], "B": paired["usage"]["B"],
                  "trigger": chosen_usage},
        "input_token_savings_vs_b_fraction": savings,
        "positive_cost_aware_pilot_gate": positive_pilot,
        "statistical_accuracy_gain_gate": (
            trigger_correct > paired["a_exact"] and
            _mcnemar_two_sided(counts["a_only"], counts["trigger_only"]) < 0.05),
        "cases": chosen_cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--policy", choices=("v1", "v2", "v3", "v4"), default="v1")
    args = parser.parse_args()
    run_dir = Path(args.run_dir).resolve()
    path = run_dir / ({"v1": "trigger_scores.json", "v2": "trigger_v2_scores.json",
                       "v3": "trigger_v3_scores.json",
                       "v4": "trigger_v4_scores.json"}[args.policy])
    if path.exists():
        raise FileExistsError(path)
    if args.policy == "v1":
        result = score_trigger(run_dir)
    else:
        if args.policy == "v2":
            from .trigger_v2 import choose_arm as chosen_rule
        else:
            from .trigger_v3 import choose_arm as chosen_rule
        manifest = json.loads((run_dir / "manifest.json").read_text())
        trigger_source = "v2" if args.policy == "v2" else "v3"
        trigger_path = Path(__file__).parent / f"trigger_{trigger_source}.py"
        if hashlib.sha256(trigger_path.read_bytes()).hexdigest() != manifest["trigger_code_sha256"]:
            raise ValueError("Trigger rule changed after prediction")
        for case in json.loads((run_dir / "selection.json").read_text()):
            if case["trigger_arm"] != chosen_rule(case):
                raise ValueError(f"Frozen trigger choice changed: {case['case_id']}")
        if args.policy == "v2":
            result = score_trigger(run_dir, chooser=chosen_rule,
                                   min_trigger_rate=0.05, max_trigger_rate=0.5,
                                   require_at_least_b=False)
        else:
            result = score_trigger(run_dir, chooser=chosen_rule,
                                   min_trigger_rate=0.0, max_trigger_rate=1.0,
                                   require_at_least_b=False,
                                   min_evaluable=80 if args.policy == "v4" else 60,
                                   require_significant=True)
    path.write_text(json.dumps(result, indent=2))
    print(json.dumps({key: value for key, value in result.items() if key != "cases"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
