#!/usr/bin/env bash
set -euo pipefail

# Capped partial Flask pilot — selects up to 20 cases if the partial baseline yields them.
# A shared API budget is split between baseline and correction phases.
# Baseline is capped at BASELINE_BUDGET; the remainder goes to correction.
# The user's --max-calls value is the total for both phases combined.
#
# Requires CODEMATE_API_KEY in the environment.
#
# Usage:
#   CODEMATE_API_KEY=sk-... bash experiments/error_to_context/run_20case_pilot.sh
#
# Flags:
#   --dry-run       skip API calls, validate paths only
#   --max-calls N   total API budget for both phases (default: 85)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
OUTPUT_DIR="${REPO_DIR}/experiments/error_to_context/runs"
MAX_CALLS=85
DRY_RUN=""
# Flask has hundreds of annotation units. Forty-five calls produce a partial
# baseline, not a full-repository prediction. Correction allows at most 20
# two-arm cases; stop if the partial baseline yields no eligible cases.
BASELINE_BUDGET=45

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN="--dry-run" ;;
        --max-calls) MAX_CALLS="$2"; shift ;;
        *) echo "Unknown: $1"; exit 1 ;;
    esac
    shift
done

cd "$REPO_DIR"

echo "=== Capped partial Flask pilot (up to 20 cases) ==="
echo "Repo:     $REPO_DIR"
echo "Output:   $OUTPUT_DIR"
echo "Total API budget: $MAX_CALLS"
echo "Baseline budget:  $BASELINE_BUDGET"
echo "Correction budget: $((MAX_CALLS - BASELINE_BUDGET))"
echo "Dry-run:  ${DRY_RUN:-no}"
echo ""

# Step 1: Preflight
echo "--- Preflight ---"
.venv/bin/python -m experiments.error_to_context.cli preflight --output-dir "$OUTPUT_DIR" $DRY_RUN
echo ""

if [ -n "$DRY_RUN" ]; then
    echo "DRY RUN: stopping after preflight"
    exit 0
fi

# Step 2: Build baseline (capped at baseline budget)
echo "--- Build Baseline ---"
.venv/bin/python -m experiments.error_to_context.cli build-baseline \
    --output-dir "$OUTPUT_DIR" --max-api-calls "$BASELINE_BUDGET"
echo ""

REMAINING=$((MAX_CALLS - BASELINE_BUDGET))
if [ "$REMAINING" -le 0 ]; then
    echo "ERROR: API budget exhausted"
    exit 1
fi

# Step 3: Select cases (zero API calls)
echo "--- Select Cases ---"
.venv/bin/python -m experiments.error_to_context.cli select-cases --output-dir "$OUTPUT_DIR"
echo ""

# Step 4: Run paired correction with remaining budget
echo "--- Run Paired Correction ---"
.venv/bin/python -m experiments.error_to_context.cli run-paired \
    --output-dir "$OUTPUT_DIR" --max-api-calls "$REMAINING"
echo ""

# Step 5: Summarize
echo "--- Summary ---"
.venv/bin/python -m experiments.error_to_context.cli summarize --output-dir "$OUTPUT_DIR"
echo ""

echo "=== Pilot complete ==="
echo "Results in: $OUTPUT_DIR"
