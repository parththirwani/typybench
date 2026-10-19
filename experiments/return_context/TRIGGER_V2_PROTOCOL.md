# Narrow source-signal trigger: disjoint prospective cases

## Development and separation

The first trigger, which retrieved memory for returned-value assignments or
yields, failed its frozen holdout gate. On 106 evaluable fastapi/openai-python/
urllib3/sphinx/gradio/haystack cases, it obtained 73 exact return types against
74 without memory and 73 with unconditional memory, while saving 7.1% input
tokens versus unconditional memory. This is a negative result.

After inspecting discordant examples across all three completed structured
studies, a narrower source-only rule selected 34 of 249 evaluable cases. Its
retrospective accuracy was 173/249 versus 165/249 without memory and 174/249
with unconditional memory. These numbers are **development evidence only**;
the rule was chosen after seeing their outcomes.

## Frozen rule and prospective set

- The trigger selects Arm B before inference iff the deterministic
  `return_memory_v1` text contains `yield line`, contains `cast(`, or matches
  `return line <number>: <capitalized identifier>(` at the start of a return
  expression. Otherwise it selects Arm A. The rule cannot use model output,
  typed reference, scores, or repository name.
- Build source-only candidates using unchanged `select_candidates` separately
  for the four cohorts: pdm/manim/capa; black/pip/pydantic;
  fastapi/openai-python/urllib3/sphinx/gradio/haystack; flask/typer/pre-commit.
  Use limit 10,000 so no cases are cut by the old sampling limit. Exclude any
  case ID in the frozen selection files for the previous return-type smoke and
  holdout runs. The 126 currently remaining IDs constitute this prospective
  case-disjoint set. Keep every one; do not replace cases after outcomes.
- Both arms use `gpt-5.4-mini`, temperature zero, one call per arm and no
  retries. Arm B adds the same deterministic memory as earlier studies. Both
  arms are run to observe counterfactual outcomes; deployed trigger cost is
  measured from only the arm selected before either call.
- Do not read typed `original_repo` files or compute scores until all paired
  predictions and usage are frozen and their SHA-256 hashes verified.

## Outcome gates and reporting

Use the existing strict AST-normalized reference match and missing-reference
rules. Report selected and evaluable denominators, A/B/trigger correct counts,
discordant cases, exact McNemar p-values, the trigger rate, and measured input
and output tokens. The **positive cost-aware pilot** gate requires at least 80
evaluable cases, trigger correct count greater than A, input-token cost below
B by at least 5%, and B selected on between 5% and 50% of evaluable cases.
Report whether the trigger also matches or exceeds B, but that is not needed
for this gate. Claim a statistically supported accuracy gain only if the
prospective two-sided exact McNemar p-value against A is below 0.05. If the
gate fails, report it without changing the rule on these cases.

This is return-type prediction, a proxy for selective explicit memory access.
It is not a mypy repair result or an official TypyBench score. The earlier
negative repair pilot and failed first trigger must remain in any report.
