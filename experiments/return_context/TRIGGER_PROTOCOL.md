# Source-signal retrieval trigger: prospective holdout

## Motivation and prior observations

In the earlier PDM/manim/capa return-type study, adding a deterministic summary of
the untyped callee changed strict reference matches from 27/48 (no memory) to
33/48 (always include memory). This was inconclusive (two-sided exact McNemar
p = 0.0703125). An exploratory source-only rule, devised after viewing those
results, selected memory when the summary contained an assignment relevant to
the returned value or a yield. On that development cohort it selected 27/48
cases and matched the always-memory arm's 33 correct answers. This is training
evidence, not a held-out result. A later unconditional-memory replication on
black/pip/pydantic was also inconclusive (64/95 versus 68/95, p = 0.2890625).

## Frozen rule and new cohort

- Repositories: fastapi, openai-python, urllib3, sphinx, gradio, haystack.
  These repositories appeared in a *different* parameter-type study, but no
  return-type results from them were used to choose this trigger.
- Use the existing source-only `select_candidates` and `build_memory` without
  changing their logic. SHA-256 rank and select at most 120 cases; the first
  six are a technical smoke set, the rest form the scored holdout.
- The trigger runs **before** model inference. It chooses B if and only if
  `return_memory` contains `assignment line` or `yield line`; otherwise it
  chooses A. It uses no typed reference, model answer, or score.
- Run both A and B for every selected case to observe the counterfactual, but
  calculate deployed selective cost as the chosen arm only. A sees the caller,
  import, and target symbol. B additionally sees `return_memory_v1`. Both use
  gpt-5.4-mini at temperature zero with one call per arm and no retries.
- Do not read typed references or score cases until both arms' responses are
  frozen on disk. Do not substitute cases after seeing the answers.

## Outcomes and decision rule

The primary outcome is strict AST-normalized equality to the existing typed
return annotation, with the same missing-reference rules as `score.py`.
Report all selected and evaluable cases, A/B/trigger accuracy, both discordant
tables, trigger rate, total input and output tokens for each policy, and the
two-sided exact McNemar tests. Extra local CPU work for creating the memory is
not measured by the cloud-token count and must be stated separately.

Call this a **positive cost-aware pilot**, not proof of general generalization,
only if at least 80 holdout cases are evaluable, the trigger chooses B on
between 10% and 90% of evaluable cases, its exact-match count exceeds A's,
its count is at least B's, and its measured cloud input-token total is at
least 5% below always-B. If these gates fail, report the failure without
changing the rule on this holdout. A statistical claim that memory improves
accuracy additionally requires p < 0.05 for the trigger-versus-A paired test.

The original nine-case mypy annotation-repair pilot remains a separate negative
result. Return-type prediction here is a proxy for choosing when explicit
knowledge-based memory is useful; it is not an official TypyBench score and
does not demonstrate a coding-agent repair benefit.
