"""Repository-level breakdown and exploratory cluster bootstrap for v6."""

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

from .score import score


def analyze(run_dir: Path, *, repetitions: int = 20_000, seed: int = 606) -> dict:
    cases = json.loads((run_dir / "selection.json").read_text())
    rows = [json.loads(line) for line in (run_dir / "rows.jsonl").read_text().splitlines()
            if line.strip()]
    by_case = defaultdict(dict)
    for row in rows:
        by_case[row["case_id"]][row["arm"]] = row
    scored = {item["case_id"]: item for item in score(run_dir)["cases"]}
    by_repo = defaultdict(lambda: {"selected": 0, "evaluable": 0, "b_input": 0,
                                   "policy_input": 0, "a_exact": 0, "b_exact": 0,
                                   "policy_exact": 0})
    for case in cases:
        repo = by_repo[case["repo"]]
        action = case["trigger_action"]
        repo["selected"] += 1
        repo["b_input"] += by_case[case["case_id"]]["B"]["input_tokens"]
        if not action.startswith("static:"):
            repo["policy_input"] += by_case[case["case_id"]][action]["input_tokens"]
        result = scored[case["case_id"]]
        if not result["evaluable"]:
            continue
        repo["evaluable"] += 1
        repo["a_exact"] += result["a_correct"]
        repo["b_exact"] += result["b_correct"]
        repo["policy_exact"] += (
            action.removeprefix("static:") == result["reference"]
            if action.startswith("static:") else
            result["a_correct" if action == "A" else "b_correct"])
    data = list(by_repo.values())
    rng = random.Random(seed)
    savings, versus_a, versus_b = [], [], []
    for _ in range(repetitions):
        sample = rng.choices(data, k=len(data))
        b_tokens = sum(repo["b_input"] for repo in sample)
        eval_count = sum(repo["evaluable"] for repo in sample)
        savings.append(100 * (1 - sum(repo["policy_input"] for repo in sample) / b_tokens))
        versus_a.append(100 * sum(repo["policy_exact"] - repo["a_exact"]
                                  for repo in sample) / eval_count)
        versus_b.append(100 * sum(repo["policy_exact"] - repo["b_exact"]
                                  for repo in sample) / eval_count)

    def interval(values):
        ordered = sorted(values)
        return [ordered[int(0.025 * repetitions)], ordered[int(0.975 * repetitions) - 1]]

    return {"by_repo": {name: {**value, "input_savings_pct":
                                100 * (1 - value["policy_input"] / value["b_input"])}
                        for name, value in by_repo.items()},
            "cluster_bootstrap_repetitions": repetitions, "seed": seed,
            "cluster_bootstrap_95pct_interval": {
                "input_savings_pct": interval(savings),
                "policy_minus_a_accuracy_pp": interval(versus_a),
                "policy_minus_b_accuracy_pp": interval(versus_b)}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(analyze(args.run_dir.resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
