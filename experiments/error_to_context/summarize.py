import os
import json
import glob
from collections import defaultdict
from .correction import CorrectionRow


def load_results(output_dir: str) -> dict[str, dict[str, CorrectionRow]]:
    rows_dir = os.path.join(output_dir, "corrections")
    if not os.path.isdir(rows_dir):
        return {}

    cases: dict[str, dict[str, CorrectionRow]] = defaultdict(dict)
    for row_file in sorted(glob.glob(os.path.join(rows_dir, "**", "row.json"), recursive=True)):
        with open(row_file) as f:
            data = json.load(f)
        cr = CorrectionRow(**data)
        cases[cr.case_id][cr.arm] = cr
    return dict(cases)


def summarize(output_dir: str) -> dict:
    cases = load_results(output_dir)
    if not cases:
        return {"error": "No results found", "cases": 0}

    both_succeed = 0
    a_only = 0
    b_only = 0
    neither = 0
    total = len(cases)

    for case_id, arms in cases.items():
        a_ok = arms.get("A") and arms["A"].clean_correction
        b_ok = arms.get("B") and arms["B"].clean_correction
        if a_ok and b_ok:
            both_succeed += 1
        elif a_ok and not b_ok:
            a_only += 1
        elif not a_ok and b_ok:
            b_only += 1
        else:
            neither += 1

    arm_a_total = sum(1 for arms in cases.values() if "A" in arms)
    arm_b_total = sum(1 for arms in cases.values() if "B" in arms)
    arm_a_clean = sum(1 for arms in cases.values() if arms.get("A") and arms["A"].clean_correction)
    arm_b_clean = sum(1 for arms in cases.values() if arms.get("B") and arms["B"].clean_correction)

    total_api_calls = sum(
        (1 for arms in cases.values() for ar in arms.values() if ar.model_response_id)
    )

    total_input_tokens = sum(
        (ar.usage_input_tokens or 0 for arms in cases.values() for ar in arms.values())
    )
    total_output_tokens = sum(
        (ar.usage_output_tokens or 0 for arms in cases.values() for ar in arms.values())
    )
    total_latency_ms = sum(
        (ar.latency_ms for arms in cases.values() for ar in arms.values())
    )

    return {
        "total_cases": total,
        "both_succeed": both_succeed,
        "a_only": a_only,
        "b_only": b_only,
        "neither": neither,
        "arm_a_clean": arm_a_clean,
        "arm_a_total": arm_a_total,
        "arm_b_clean": arm_b_clean,
        "arm_b_total": arm_b_total,
        "paired_diff_pct": ((arm_b_clean / arm_b_total) - (arm_a_clean / arm_a_total)) * 100 if arm_a_total and arm_b_total else None,
        "total_api_calls": total_api_calls,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_latency_ms": total_latency_ms,
    }