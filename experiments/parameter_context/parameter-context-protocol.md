# Cross-file call evidence for parameter typing

## Question

Does retrieving an observed call from another file improve prediction of an untyped function parameter? This tests a small, explicit repository-memory item: a prior use of the function. It is a type-prediction study, not a mypy repair or an official TypyBench score.

## Frozen design, before cloud calls or typed-reference access

- Data: the TypyBench dev repositories `fastapi`, `openai-python`, `urllib3`, `sphinx`, `gradio`, and `haystack`. Only `repo_without_types` is available to selection and inference. The typed `original_repo` copies must remain unopened and unextracted until both arms' predictions are frozen.
- The source-only selector finds top-level unannotated callees with a cross-file caller. It retains a parameter only when the caller explicitly supplies a positional or named argument. It chooses one parameter and one call per callee by SHA-256 rank. A function or parameter with no unambiguous matched call is excluded. The selector currently yields 96 cases. Take all 96 in SHA-256 case order. The first six form a technical smoke set; the other 90 form the holdout.
- Arm A sees the target function's untyped definition and parameter name. Arm B sees exactly the same prompt and system message, plus the caller's import, function, and matched call expression. Both use `gpt-5.4-mini`, temperature zero, one call per arm, no retries or revisions. A malformed response counts as incorrect.
- Before reference access, save the selected source evidence, prompt hashes, raw model responses, validity, usage, and a SHA-256 freeze of all rows. Do not substitute cases after observing predictions or references.

## Analysis

The primary outcome is exact AST-normalized equality between the predicted parameter type and the unique annotation on the corresponding top-level function parameter in `original_repo`. Cases without a unique annotated reference are unevaluable, with reasons reported. Both arms stay in the paired denominator if one fails. The primary test is two-sided exact McNemar. A positive result requires at least 50 evaluable holdout cases, Arm B exact accuracy greater than Arm A, and p < 0.05. The six smoke cases do not enter the primary test. Report extra input tokens for B and inspect every discordant pair. No prompt adjustment is allowed after seeing smoke or holdout answers.

This follows two inconclusive return-type experiments and an underpowered mypy-repair pilot. A positive result would support the narrower claim that one retrieved call can help parameter-type inference. It would not establish a benefit for automated repair or justify a cost-aware trigger without a separate trigger evaluation.
