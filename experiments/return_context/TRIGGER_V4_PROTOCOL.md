# Repository-disjoint validation of the unchanged v3 trigger

## Locked method

This test reuses `trigger_v3.choose_arm` exactly. It chooses B before inference
when `return_memory_v1` contains an assignment to a returned name, a yield,
`cast(`, or a return expression starting with a capitalized call. Otherwise
it chooses A. No threshold, prompt, memory builder, or model setting will be
changed after the prior v3 test.

## New repositories and reference isolation

- Source-only cohort, fixed before typed-reference extraction: poetry, rich,
  flake8, nicegui, pandas-ai, deepface, gptme, appworld. None appeared in the
  earlier return-type predictions. The stripped source selector yields 125
  unique top-level callees with cross-file callers. Keep all selected cases.
- Use unchanged `select_candidates` at its default 2,400-character caller
  limit and SHA-256 case ranking. Build the same at-most-1,000-character
  `return_memory_v1` only from `repo_without_types`.
- Run A and B independently for every case using `gpt-5.4-mini`, temperature
  zero, one call per arm, no retries. A receives caller/import/target; B adds
  the deterministic memory. The trigger chooses its arm before either call.
- Save selection, prompts' hashes, raw predictions, validity, token usage,
  and SHA-256 freeze. Do not extract or inspect any `original_repo` file from
  the downloaded official dataset ZIP until the paired rows are frozen.
  After freezing, extract only the exact typed `.py` files needed to score
  selected callees. Refuse path traversal and overwrites.

## Primary decision

Use the existing strict AST-normalized reference equality, counting invalid
model answers as incorrect. Report all selected and evaluable denominators,
missing-reference reasons, A/B/trigger exact matches, paired two-sided exact
McNemar p-values, input and output tokens, trigger rate, and discordant cases.
The unchanged trigger passes this repository-disjoint validation only if at
least 80 cases are evaluable, it exceeds A's exact-match count with p < 0.05
against A, and its input-token total is at least 5% below always-B. The
trigger's correctness versus B must also be reported. If the gate fails,
report failure without revising this holdout's rule.

This is a function-level return-type inference proxy for selective explicit
memory. It is not an official TypyBench TypeSim or TypeCheck score and does not
demonstrate a coding-agent repair benefit. The earlier negative trigger tests
remain part of the full evidence record.
