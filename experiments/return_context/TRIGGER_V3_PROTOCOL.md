# Combined source-signal trigger: longer-caller prospective test

## Why this test exists

The narrow v2 rule passed a descriptive cost gate on 105 evaluable cases but
captured only two of 13 B-only successes. Inspecting already-scored cases
showed that assignment/yield and cast/constructor signals catch different
memory benefits. The union of those signals is a development choice made
after seeing the earlier outcomes. No accuracy estimate from those outcomes
is a validation result for v3.

## Frozen selection and rule

- Use the same 15 typed-reference-available repositories as the earlier
  return studies. Run unchanged `select_candidates` except for setting the
  allowed caller function span to 7,200 characters instead of 2,400. Keep
  its SHA-256 ranking and one-caller-per-callee rule.
- Exclude **every** case ID in previous return-type smoke and holdout
  selections, including the v2 residual holdout. The source-only dry-run
  found 90 new function IDs. Keep all 90; do not substitute cases.
- Compute the same `return_memory_v1` from stripped source. Before inference,
  choose B iff it has an `assignment line`, a `yield line`, `cast(`, or a return
  expression starting with a capitalized call (`return line <n>: TypeName(`).
  Otherwise choose A. The rule cannot read a typed reference, model output,
  repository name, or score.
- Run paired A and B calls for all cases with `gpt-5.4-mini`, temperature zero,
  no retries. A sees caller/import/target; B gets the same plus memory.
  Record the trigger's deployed cost from only the preselected arm. Freeze
  paired predictions, hashes, validity, and usage before opening typed
  reference files.

## Primary decision

Use strict AST-normalized return-type equality against a unique annotated
top-level reference function. Include invalid model answers in the paired
denominator as incorrect and report missing-reference reasons separately.
The v3 result is a positive, statistically supported cost-aware pilot only if
at least 60 cases are evaluable, the trigger scores more exact matches than
A with two-sided exact McNemar p < 0.05, and measured input-token use is at
least 5% below always-B. Report A, B, trigger, token totals, trigger rate,
discordants, and the previous negative studies regardless of outcome. Do not
revise the rule after scoring these cases.

This remains a type-inference proxy, not a coding-agent repair result or an
official TypyBench TypeSim/TypeCheck score. Function IDs are disjoint, but
repositories overlap with the development cohorts. The longer-caller sample
may have a different difficulty distribution and should be labeled as such.
