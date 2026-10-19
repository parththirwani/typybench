# Selective memory for repository-level type inference

19 October 2026. This is a local TypyBench-derived experiment, not an official
TypeSim or TypeCheck score.

## Result

The frozen v2 pilot passed its predeclared cost-aware gate, but it did **not**
establish a reliable accuracy gain for the trigger. On 105 evaluable,
function-disjoint cases, the no-memory arm predicted 69 exact return types,
the always-memory arm predicted 78, and the pre-inference trigger predicted 70.
The trigger chose memory on 13/105 evaluable cases (17/126 selected cases) and
used 49,082 input tokens, 12.7% less than always-memory's 56,193. Its 70-versus-
69 difference from no memory has an exact two-sided McNemar p-value of 1.0.
Always-memory's 78-versus-69 difference has a nominal p-value of 0.0490.

| Policy | Exact / 105 | Input tokens across all 126 selected cases | Input + output tokens |
| --- | ---: | ---: | ---: |
| No memory (A) | 69 | 47,980 | 50,124 |
| Always memory (B) | 78 | 56,193 | 57,762 |
| Source-signal trigger | 70 | 49,082 | 51,185 |

The trigger saves 7,111 input tokens (12.7%) and 6,577 total tokens (11.4%)
against B, but it gives up eight of B's nine net additional exact matches over
A. Its cost is also 1,102 input tokens above A. This is a measured
cost/accuracy point, not evidence that the present rule is optimal. The
observed latency was 126.1 seconds for the selected-arm calls versus 123.5
seconds for B; lower token use did not lower aggregate latency in this run.

## What we ran

1. Starting only from `repo_without_types`, the existing selector found
   cross-file calls to top-level functions without return annotations. We
   excluded every function ID used in earlier return-type smoke and holdout
   selections. That left 126 cases across 15 repositories. The first source-
   signal trigger used a different 114-case cohort and failed its own gate;
   those cases were not reused here.
2. The deterministic memory summarized the untyped callee's return and yield
   expressions plus assignments to returned names, capped at 1,000
   characters. Arm A saw the caller, import, and target symbol. Arm B saw the
   same prompt plus this memory. Both used `gpt-5.4-mini`, temperature zero,
   one cloud call each, with no retries or hand-edited answers.
3. Before any model call, v2 chose B only when the source summary contained a
   yield, `cast(`, or a return expression starting with a capitalized call
   such as `Path(...)`. The decision did not use model answers, typed
   references, or scores. We ran both arms to measure the counterfactual but
   charged the trigger only for its preselected arm.
4. We froze 252 successful, parse-valid predictions, their token usage, and
   SHA-256 hashes. Only then did the scorer read `original_repo`. It excluded
   21 cases because there was no unique annotated reference function, leaving
   105 paired, evaluable cases. Strict AST-normalized type-string equality was
   the outcome.

The [frozen protocol](TRIGGER_V2_PROTOCOL.md), [selection and manifest](runs/trigger_v2_holdout_20261019/manifest.json), [paired scores](runs/trigger_v2_holdout_20261019/scores.json), and [trigger scores](runs/trigger_v2_holdout_20261019/trigger_v2_scores.json) preserve the method and results. Recompute both scores without overwriting the archive with:

```sh
.venv/bin/python - <<'PY'
from pathlib import Path
from experiments.return_context.score import score
from experiments.return_context.trigger_score import score_trigger
from experiments.return_context.trigger_v2 import choose_arm
run = Path('experiments/return_context/runs/trigger_v2_holdout_20261019')
paired = score(run)
trigger = score_trigger(run, chooser=choose_arm, min_trigger_rate=0.05,
                        max_trigger_rate=0.5, require_at_least_b=False)
print(paired['a_exact'], paired['b_exact'], trigger['trigger_exact'])
print(trigger['usage']['trigger']['input_tokens'], trigger['positive_cost_aware_pilot_gate'])
PY
```

## How this fits with earlier results

- The original nine-site annotation-repair pilot found 6/9 clean corrections
  in both arms. Retrieval added 1,046 input tokens and no valid repair gain.
- The parameter-type holdout found 48/90 exact without memory and 50/90 with
  one retrieved call (p = 0.6875).
- The first two structured return-type cohorts favored memory by 6/48 and
  4/95 cases, but neither paired difference was significant (p = 0.0703 and
  p = 0.2891).
- The first source-signal trigger failed prospectively: 73/106 versus 74/106
  for no memory, although it saved 7.1% input tokens against always-memory.
- The v2 rule was chosen after examining those previous outcomes. Its 126
  cases are function-disjoint from their selections, but some share
  repositories. The nominal p = 0.0490 for unconditional memory must be read
  alongside this sequence of studies, not as a single untouched hypothesis
  test. The evaluated cases are concentrated in pip, black, and pydantic.
- A subsequent v3 test combined the source signals on 90 new, longer-caller
  cases. Of 76 evaluable cases, A scored 56, B scored 63, and the trigger
  scored 61. The trigger's paired p-value against A was 0.2266 and it saved
  only 2.9% input tokens against B. It failed its frozen gate. See the
  [v3 protocol](TRIGGER_V3_PROTOCOL.md) and [v3 scores](runs/trigger_v3_holdout_20261019/trigger_v3_scores.json).

## Interpretation and research use

There is now direct local evidence for two parts of the proposed research
question. Explicit, typed-reference-free memory can change a model's answer
for the better on some repository-level type decisions; in the v2 residual
cohort, unconditional memory gained nine net exact matches. Sending that
memory on every case costs 17.1% more input tokens than A. A deterministic
source signal can skip most memory injections and cut this overhead, but the
current signal misses most cases that benefit. That gap is the concrete target
for a learned or better-calibrated decision model.

As a non-deployable upper bound, a selector that knew each reference answer
could choose B on exactly the 13 B-only cases and A elsewhere. It would score
82/105 while using 49,019 input tokens. This uses ground truth to make the
decision, so it is **not** an experimental trigger result. It quantifies the
headroom between the current rule's 70/105 and a perfect selection policy.

A proposal can state the measured trade-off above, then propose a small
decision model trained on source-only features and a cost-sensitive objective
to predict when the expected error reduction justifies memory injection.
Future evaluation should pre-register a new repository-level holdout, compare
against both never and always retrieving, and report accuracy, tokens, and
selective-policy regret. These results do not prove that a graph decoder,
reinforcement-learning post-training, or coding-agent repair memory will work;
those remain separate research questions.

No credential value appears in the saved artifacts or this report. One earlier
114-case attempt in `runs/trigger_holdout_20261019/` froze transport failures
because the workspace network sandbox could not resolve the endpoint. We
preserved that failed artifact and reran the unchanged first-trigger protocol
after a successful connectivity check. The v2 study has 252 successful calls.
