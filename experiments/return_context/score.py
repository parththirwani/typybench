"""Score frozen predictions; this is the only module that reads typed references."""

import argparse
import ast
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path


DATA_ROOT = Path("/home/too_geeky/research/typybenchdata")


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _reference_return(case: dict) -> tuple[str | None, str | None]:
    path = DATA_ROOT / case["repo"] / "original_repo" / case["callee_file"]
    if not path.is_file():
        return None, "Reference file missing"
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return None, "Reference file has syntax error"
    matches = [node for node in tree.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
               and node.name == case["callee_symbol"]]
    if len(matches) != 1 or matches[0].returns is None:
        return None, "No unique annotated reference function"
    annotation = matches[0].returns
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        try:
            annotation = ast.parse(annotation.value, mode="eval").body
        except SyntaxError:
            pass
    return ast.unparse(annotation), None


def _mcnemar_two_sided(a_only: int, b_only: int) -> float:
    discordant = a_only + b_only
    if discordant == 0:
        return 1.0
    tail = sum(math.comb(discordant, k) for k in range(min(a_only, b_only) + 1))
    return min(1.0, 2.0 * tail / (2 ** discordant))


def score(run_dir: Path) -> dict:
    selection_bytes = (run_dir / "selection.json").read_bytes()
    rows_bytes = (run_dir / "rows.jsonl").read_bytes()
    manifest = json.loads((run_dir / "manifest.json").read_text())
    frozen = json.loads((run_dir / "predictions_frozen.json").read_text())
    if _hash(selection_bytes) != manifest["selection_sha256"]:
        raise ValueError("Selection changed after prediction")
    if _hash(rows_bytes) != frozen["rows_sha256"]:
        raise ValueError("Predictions changed after freeze")
    cases = json.loads(selection_bytes)
    rows = [json.loads(line) for line in rows_bytes.splitlines() if line.strip()]
    if len(rows) != frozen["rows"] or len(rows) != 2 * len(cases):
        raise ValueError("Paired prediction row count does not match frozen selection")
    by_case = defaultdict(dict)
    for row in rows:
        if row["arm"] in by_case[row["case_id"]]:
            raise ValueError(f"Duplicate arm: {row['case_id']} {row['arm']}")
        by_case[row["case_id"]][row["arm"]] = row
    if set(by_case) != {case["case_id"] for case in cases}:
        raise ValueError("Prediction cases do not match selection")

    scored = []
    both = a_only = b_only = neither = 0
    missing = 0
    for case in cases:
        arms = by_case[case["case_id"]]
        if set(arms) != {"A", "B"}:
            raise ValueError(f"Missing paired arm: {case['case_id']}")
        truth, reason = _reference_return(case)
        if truth is None:
            missing += 1
            scored.append({"case_id": case["case_id"], "evaluable": False, "reason": reason})
            continue
        a_ok = arms["A"]["valid"] and arms["A"]["prediction"] == truth
        b_ok = arms["B"]["valid"] and arms["B"]["prediction"] == truth
        if a_ok and b_ok:
            both += 1
        elif a_ok:
            a_only += 1
        elif b_ok:
            b_only += 1
        else:
            neither += 1
        scored.append({
            "case_id": case["case_id"], "evaluable": True,
            "reference": truth, "A": arms["A"]["prediction"],
            "B": arms["B"]["prediction"], "a_correct": bool(a_ok),
            "b_correct": bool(b_ok),
        })
    evaluable = both + a_only + b_only + neither
    usage = {arm: {
        "input_tokens": sum(row["input_tokens"] or 0 for row in rows if row["arm"] == arm),
        "output_tokens": sum(row["output_tokens"] or 0 for row in rows if row["arm"] == arm),
        "latency_ms": sum(row["latency_ms"] or 0 for row in rows if row["arm"] == arm),
        "missing_usage_rows": sum(row["input_tokens"] is None for row in rows if row["arm"] == arm),
    } for arm in ("A", "B")}
    result = {
        "phase": manifest["phase"], "selected": len(cases),
        "evaluable": evaluable, "missing_reference": missing,
        "both": both, "a_only": a_only, "b_only": b_only,
        "neither": neither,
        "a_exact": both + a_only, "b_exact": both + b_only,
        "paired_difference_pct": ((b_only - a_only) / evaluable * 100) if evaluable else None,
        "mcnemar_p_two_sided": _mcnemar_two_sided(a_only, b_only),
        "usage": usage, "cases": scored,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    run_dir = Path(args.run_dir).resolve()
    output = run_dir / "scores.json"
    if output.exists():
        raise FileExistsError(output)
    result = score(run_dir)
    output.write_text(json.dumps(result, indent=2))
    summary = {key: value for key, value in result.items() if key != "cases"}
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
