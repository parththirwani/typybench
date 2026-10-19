# A cost-aware memory trigger on unseen TypyBench repositories

19 October 2026. This is a function-level return-type inference experiment
derived from [TypyBench](https://github.com/typybench/typybench). It is not an
official TypeSim or TypeCheck score.

## Main result

The unchanged source-signal trigger passed its frozen, repository-disjoint
gate. Among 110 evaluable functions from eight repositories not used in the
earlier return-type studies, it predicted 84 exact return types. The
no-memory arm predicted 73 and the always-memory arm predicted 86. The
trigger's 11-case gain over no memory is 10 percentage points, with a
case-level two-sided exact McNemar p-value of 0.00342 (12 trigger-only wins,
one A-only win). It used 49,192 input tokens across all 125 selected cases,
3,005 fewer than always-memory's 52,197, a 5.76% reduction.

| Policy | Exact / 110 evaluable | Input tokens / 125 selected | Input + output tokens |
| --- | ---: | ---: | ---: |
| No memory (A) | 73 | 44,291 | 46,339 |
| Always memory (B) | 86 | 52,197 | 53,646 |
| Trigger | 84 | 49,192 | 50,945 |

The trigger chose memory for 62/125 selected cases, or 57/110 evaluable
cases. It gave up two exact matches relative to always-memory. Its paired
comparison with B had three B-only wins and one trigger-only win (p = 0.625).
This does not establish formal non-inferiority to B. Output tokens were higher
for the trigger than B, but input-plus-output tokens still fell by 5.03%.

## What the trigger does

For each cross-file call, the program builds a bounded, typed-reference-free
summary of the untyped callee's return/yield expressions and assignments to
returned names. Before the model sees a prompt, the trigger chooses to
include that memory only if the summary contains an assignment, a yield,
`cast(`, or a return expression beginning with a capitalized call. Otherwise
the model sees the caller, import, and target symbol without the summary.
The rule is in [`trigger_v3.py`](trigger_v3.py). It was fixed after the v3
study and reused unchanged here; the v4 manifest records its SHA-256 hash.

## Protocol and audit trail

The [v4 protocol](TRIGGER_V4_PROTOCOL.md) fixed the rule, eight new
repositories, source-only selection, model, paired prompts, success gate, and
reference isolation before this run. `select_candidates` found 125 unique
top-level callees with cross-file callers in poetry, rich, flake8, nicegui,
pandas-ai, deepface, gptme, and appworld. No typed reference file for these
cases existed locally before inference.

We made one independent `gpt-5.4-mini` call per arm, per case, at temperature
zero with no retry or manual answer correction. Both arms ran for every case
to observe the counterfactual. The deployed trigger's cost uses only its
preselected arm. All 250 calls succeeded, returned parse-valid predictions,
and reported token usage. The selector and paired-row SHA-256 hashes matched
the frozen manifest before typed references were opened.

The [official dataset ZIP](https://github.com/typybench/typybench#dataset-download-link)
was downloaded from the project link. Its local archive had 656,943,500 bytes
and SHA-256 `312b0885a208849ee0225d8fc77f3c6a14df3c7477a67d7a1715d37d1dea239a`.
The prediction freeze was recorded at 00:12:13 UTC; selective extraction
followed at 00:12:24 UTC. The extractor copied 52 selected typed `.py` files
without overwriting existing files and found one missing archive member. The
scorer marked 15/125 cases unevaluable: 14 lacked a unique annotated
reference function and one lacked its reference file. It kept every other
case in the paired denominator, including incorrect predictions.

The main artifacts are the [manifest](runs/trigger_v4_holdout_20261019/manifest.json),
[frozen predictions](runs/trigger_v4_holdout_20261019/predictions_frozen.json),
[extraction record](runs/trigger_v4_holdout_20261019/extraction_manifest.json),
[paired scores](runs/trigger_v4_holdout_20261019/scores.json), and
[trigger scores](runs/trigger_v4_holdout_20261019/trigger_v4_scores.json).
Recomputing both score functions from the frozen files reproduced the saved
JSON exactly. The full experiment suite passes all 94 tests.

The accuracy gain occurred in several repositories, not one: appworld gained
three exact matches over A, flake8 three, gptme four, and nicegui one;
deepface and rich tied. Poetry had one evaluable case that neither arm got
right; pandas-ai had no evaluable case. These are small repository-level
samples. The case-level p-value treats functions as independent, which may
understate uncertainty when functions from one repository share patterns.

## How to use this result in the research proposal

This is evidence that a small, deterministic decision trigger can make
explicit repository memory worth its cloud-token cost in a controlled
type-inference task. A precise proposal sentence is:

> In a local TypyBench-derived pilot on 110 evaluable functions from new
> repositories, a source-signal trigger improved exact return-type matches
> from 73 to 84 over no retrieval while using 5.8% fewer input tokens than
> always including the same memory.

The next research step is to replace this hand-written rule with a small,
cost-sensitive decision model. Its input should remain available before
expensive retrieval or generation. Its outcome should reward correction
quality and charge for memory tokens, latency, and escalation. The model
should be tested on newly held-out repositories and then on genuine coding-
agent repair trajectories, where memory is written from verified or failed
repairs. That is where the user's larger read/write memory proposal must be
validated. The current study does not prove a graph decoder, reinforcement-
learning post-training, or a coding-agent repair benefit.

## Earlier results remain part of the record

The first nine-site annotation-repair pilot found no retrieval gain: both arms
had six clean corrections. The initial parameter-type and return-type
proxies were inconclusive. The first source-signal trigger failed on its own
106-case holdout. A narrower v2 trigger passed a descriptive cost gate but
gained only one exact match over A (p = 1.0). The combined v3 trigger then
failed its longer-caller test: 61 versus 56 exact matches, p = 0.227, and
only 2.9% input-token savings against B. This v4 test reused that same v3
rule on new repositories; it was not selected by looking at v4 reference
answers. Full earlier details are in the [prior report](DECISION_TRIGGER_REPORT.md).
