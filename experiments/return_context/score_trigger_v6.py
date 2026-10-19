"""Score the frozen v6 policy against untouched reference annotations."""

import argparse
import json
from pathlib import Path

from .predict_trigger_v6 import _code_hashes
from .score_trigger_v5 import score_v5
from .trigger_v6 import choose_action


def score_v6(run_dir: Path) -> dict:
    return score_v5(run_dir, chooser=choose_action, code_hashes=_code_hashes,
                    study="type_bearing_trigger_v6", min_evaluable=100,
                    min_saving_pct=20.0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    output = run_dir / "v6_scores.json"
    if output.exists():
        raise FileExistsError(output)
    result = score_v6(run_dir)
    output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
