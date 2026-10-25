# Four return-type inference policies on one repository cohort

20 October 2026. This report compares four ways to answer the same return-type
question on the 151 functions selected for the v6 TypyBench-derived study. The
functions came from six previously unused repositories. Typed references were
opened only after predictions were frozen. Of the 151 selected functions, 116
had an evaluable annotated reference. This is a strict, function-level
return-annotation comparison, not an official TypyBench TypeSim or TypeCheck
score.

## What each policy does

| Policy | Decision for each function | Cloud calls in a deployed system |
| --- | --- | ---: |
| No memory (A) | Ask `gpt-5.4-mini` using the caller, import, and target symbol, without the callee's return-memory summary. | 1 |
| Always memory (B) | Ask the same model with the same base prompt plus a bounded summary of the untyped callee's returns and related assignments. | 1 |
| Source-signal memory trigger | Use the fixed v3 rule to choose A or B. It chooses B when the summary contains an assignment, yield, `cast(`, or a constructor-style return. | 1 |
| Static analysis plus selective memory | Answer directly when a conservative source-AST rule yields a return type. Otherwise choose B only for specified type-bearing source signals and A for the rest. | 0 for a static answer; 1 otherwise |

The third policy does **not** use an LLM to make the memory decision. Its
decision is a deterministic rule; the selected A or B branch makes an LLM
call. The fourth policy is also deterministic. Neither is a trained decision
model.

## Same-cohort results

| Policy | Exact matches / 116 evaluable | Accuracy | Input tokens / 151 selected | Total tokens | Input saving vs always memory |
| --- | ---: | ---: | ---: | ---: | ---: |
| No memory (A) | 83 | 71.6% | 57,333 | 59,788 | 14.95% |
| Always memory (B) | 87 | 75.0% | 67,413 | 69,119 | 0% |
| Source-signal memory trigger | 83 | 71.6% | 62,824 | 65,034 | 6.81% |
| Static analysis plus selective memory | 87 | 75.0% | 44,690 | 46,379 | 33.71% |

The older source-signal rule chose B for 61 functions and A for 90. The
static-plus-selective rule made 41 static answers, chose A for 77 functions,
and chose B for 33. Twenty-eight static answers had evaluable references;
all 28 matched exactly. The remaining 13 static answers had no evaluable
reference. Static answers incurred no cloud-model tokens in
the policy-cost calculation.

The static-plus-selective policy saved 22,723 input tokens compared with
always memory, while matching its 87 exact answers. The source-signal
trigger saved 4,589 input tokens but matched no memory's 83 exact answers
on this cohort. Its four wins over A were offset by four losses. The
static-plus-selective policy's four-case gain over A did not meet the v6
study's predeclared significance gate (two-sided exact McNemar p = 0.344).
Matching B's total is also not proof of equivalence: the static-plus-selective
policy and B each had three case-level wins over the other.

## How the comparison was calculated

The v6 study called `gpt-5.4-mini` independently for both A and B on every
selected function, at temperature zero and with one attempt per arm. Those
302 calls let us score the counterfactual answer and cloud token usage for
either branch. The v6 policy's choices were fixed before inference. For this
report, the older, previously published v3 `choose_arm` rule was applied to
the saved v6 selection, A/B predictions, and token records. It made no new
LLM calls and did not change the frozen answers.

Accuracy uses only the 116 functions with unique annotated references.
Token totals include all 151 selected functions, including those without an
evaluable reference. Each policy's token figure counts only the arm it would
choose in deployment; the actual research run made both A and B calls to
measure the counterfactuals. Local AST parsing, source indexing, and memory
construction are excluded from cloud-token totals. These figures therefore
do not measure deployed wall-clock latency or total compute cost.

The older trigger's 83/116 and 6.81% figures here are a **secondary replay
on the v6 cohort**, not its original v4 result. In the separate v4 study,
the same trigger scored 84/110 versus 73/110 for A and 86/110 for B, with
5.76% input-token savings. The v4 and v6 cohorts differ, so their accuracy
figures must not be pooled or treated as a controlled before-and-after test.

## Interpretation

On the shared v6 cases, simple static answers account for a substantial
part of the cost reduction, and the more selective source rule avoids some
memory prompts. The four-way table supports a cloud-token result: the
static-plus-selective policy used about one-third fewer input tokens than
always memory while achieving the same number of exact answers on this
cohort. It does not show a statistically established accuracy advantage over
no memory, formal non-inferiority to always memory, or a benefit for automated
repair. A useful next test would set an acceptable accuracy-loss margin
in advance and evaluate the four policies on another repository-disjoint
cohort, then measure full latency and repair outcomes.

## Sources and reproducibility

- [v6 report](decision-trigger-v6-report.md) and [locked protocol](trigger-v6-protocol.md)
- [v4 report](decision-trigger-v4-report.md) and [older source-signal rule](trigger_v3.py)
- [v6 frozen predictions](runs/trigger_v6_holdout_20261020/predictions_frozen.json), [selection](runs/trigger_v6_holdout_20261020/selection.json), and [scores](runs/trigger_v6_holdout_20261020/v6_scores.json)
- The same-cohort replay uses `analyze(run_dir, chooser=choose_arm)` from `analyze_v5_development.py` and `trigger_v3.py` on the frozen v6 run directory.
