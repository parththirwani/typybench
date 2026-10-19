# Selective memory saved one third of cloud input tokens on new repositories

20 October 2026. This is a function-level return-type inference study derived
from the [official TypyBench dataset](https://github.com/typybench/typybench).
The policy and [protocol](TRIGGER_V6_PROTOCOL.md) were fixed before inference
and before typed references for this cohort were extracted. Six previously
unused repositories contributed selected cases: DB-GPT, phidata, taipy,
gpt-pilot, LLaMA-Factory, and Pillow. The source-only selector found no
eligible vnpy cases, although vnpy was in the planned cohort.

## Result and decision

The policy inferred 87 exact return types among 116 evaluable functions, the
same count as always including memory. It used 44,690 input tokens across all
151 selected functions, versus 67,413 for always-memory: 22,723 fewer, or
33.71% less. Input-plus-output tokens fell by 32.90%. The no-memory arm got
83 exact types. The policy's four-case gain over no memory was not
statistically significant on the case-level exact McNemar test (p = 0.344),
so the predeclared substantial-saving **and accuracy** gate failed. The
policy-versus-always-memory paired comparison had three wins and three losses
(p = 1.0); equal totals do not prove statistical equivalence.

| Policy | Exact / 116 evaluable | Input tokens / 151 selected | Total tokens |
| --- | ---: | ---: | ---: |
| No memory | 83 | 57,333 | 59,788 |
| Always memory | 87 | 67,413 | 69,119 |
| Static + selective memory | 87 | 44,690 | 46,379 |

The frozen policy chose 41 static answers, 77 caller-only requests, and 33
requests with bounded return memory. Twenty-eight static cases had evaluable
references; all 28 were correct. Of the 35 unevaluable selected cases, 31
lacked a unique annotated reference function and four depended on one file
absent from the archive. The reference extractor copied 85 of 86 selected
typed files after the prediction freeze. All 302 A/B calls completed with
token usage.

## Robustness and limitations

Every contributing repository used fewer input tokens than always-memory.
Savings ranged from 16.8% in Pillow to 79.4% in phidata. Accuracy varied:
the policy gained two exact matches over no memory in each of DB-GPT,
LLaMA-Factory, and phidata, lost two in Pillow, and tied in gpt-pilot and
taipy. A 20,000-resample exploratory bootstrap that sampled the six
repositories as clusters gave a 95% interval of 22.0% to 53.5% for input-token
savings. Its interval for the policy's accuracy difference from always-memory
was -4.4 to +3.0 percentage points. These intervals are sensitive to the
small number of repositories and are not a predeclared non-inferiority test.

The benchmark compares strict return-annotation strings after AST
normalization; equivalent aliases can score differently. Local AST analysis,
source indexing, and reference-free memory construction are not counted in
cloud tokens. The study does not measure wall-clock savings of a deployed
system, official TypyBench TypeSim/TypeCheck, or coding-agent repair quality.

## Audit trail and interpretation

The [manifest](runs/trigger_v6_holdout_20261020/manifest.json),
[frozen predictions](runs/trigger_v6_holdout_20261020/predictions_frozen.json),
[reference extraction record](runs/trigger_v6_holdout_20261020/extraction_manifest.json),
and [scores](runs/trigger_v6_holdout_20261020/v6_scores.json) retain the
run. The dataset archive SHA-256 matches the manifest and extraction record.
Recomputing the scores from the frozen files reproduced the saved JSON.

The v4 study showed a statistically significant accuracy gain with a smaller
5.8% input saving. The v5 policy saved 15.9% on a fresh cohort but did not
show an accuracy gain. V6 strengthened the cost result to 33.7% while matching
always-memory's exact-match count on another fresh cohort. These are
different policies and cohorts, so their accuracy claims should not be
combined. The next useful test should predeclare an acceptable accuracy-loss
margin and validate it on further unseen repositories, or move to verified
coding-agent repair trajectories where memory read decisions are the target
behavior.
