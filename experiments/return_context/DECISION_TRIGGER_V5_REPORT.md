# Static answers and selective memory on six fresh repositories

20 October 2026. The v5 protocol and policy were fixed before 258 cloud calls
and before any typed reference files for this cohort were extracted. The
functions came from supervision, gpt4free, paper-qa, vllm, agents, and
private-gpt. This is the same return-type inference proxy as v4, not an
official TypyBench TypeSim or TypeCheck score.

## Result

The policy saved 9,350 input tokens (15.90%) and 9,376 input-plus-output
tokens (15.53%) relative to always including return memory. It predicted
69 exact types among 105 evaluable functions, compared with 66 for no memory
and 71 for always-memory. The policy gain over no memory was three cases;
its case-level exact McNemar p-value was 0.508. The predeclared success gate
therefore failed, even though the savings exceeded its 15% threshold.

| Policy | Exact / 105 | Input tokens / 129 selected | Total tokens |
| --- | ---: | ---: | ---: |
| No memory | 66 | 48,372 | 50,510 |
| Always memory | 71 | 58,790 | 60,357 |
| Static + selective memory | 69 | 49,440 | 50,981 |

The policy made 18 static selections, 30 no-memory selections, and 81 memory
selections. Twelve static selections had evaluable references, and all twelve
were correct. Twenty-four selected cases lacked a unique annotated reference
function. All 50 required typed files were extracted after the prediction
freeze; no selected file was missing from the archive. Both A and B were run
once for every case, with complete token usage and no failed calls.

Against always-memory, the policy lost two exact matches and gained none.
This is a small sample of discordant outcomes and does not establish
non-inferiority.

## Where the gain changed

Memory improved exact matches in eight cases and harmed three against the
no-memory arm. The v3 source-signal rule sent two of the harmful cases to
memory: a list accumulated from `[]` and a numeric array calculated by
arithmetic. It missed two helpful cases with direct qualified calls. This
suggests that the next trigger should distinguish a typed constructor or
module call from an uninformative assignment. The static branch worked on
simple return patterns, but it covered only twelve evaluable cases in this
cohort, versus 23 in the v4 development run.

By repository, policy versus no-memory exact matches were 34 versus 34 in
vllm, 14 versus 14 in supervision, 15 versus 13 in paper-qa, 1 versus 1 in
gpt4free, 4 versus 4 in agents, and 1 versus 0 in private-gpt. The practical
accuracy gain is concentrated in two repositories, and 19 of vllm's 69
selected functions lacked an annotated reference.

## Audit trail and next step

The [locked protocol](TRIGGER_V5_PROTOCOL.md), [manifest](runs/trigger_v5_holdout_20261020/manifest.json),
[frozen predictions](runs/trigger_v5_holdout_20261020/predictions_frozen.json),
[reference extraction record](runs/trigger_v5_holdout_20261020/extraction_manifest.json),
and [scores](runs/trigger_v5_holdout_20261020/v5_scores.json) preserve the run.
The official archive SHA-256 was
`312b0885a208849ee0225d8fc77f3c6a14df3c7477a67d7a1715d37d1dea239a`.
The selector later gained package mappings for the v6 cohort; its exact v5
version is preserved in [frozen_v5_select.py](frozen_v5_select.py), whose hash
matches the v5 manifest. Recomputing v5 scores against that snapshot
reproduces the saved JSON.

The next test should use a new repository cohort and a frozen rule that asks
for memory when its source summary contains type-bearing evidence, while
using static answers where syntax supports them. The v5 run now serves as
development data for that rule; it is not a successful replication of v4's
statistically significant accuracy gain.
