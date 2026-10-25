# Structured-memory replication (frozen before reference access)

The initial PDM/manim/capa holdout favored Arm B (33/48 versus 27/48 exact), but its exact two-sided McNemar p-value was 0.0703125. This is inconclusive. The method is **unchanged** in this independent replication. The typed reference copies of the new repositories must remain unopened and unextracted until all predictions are frozen.

## Cohort and split

- Source repositories, fixed in advance: `black`, `pip`, `pydantic` (TypyBench dev split). No old-cohort cases may be pooled into this replication's primary analysis.
- Use `select_candidates` exactly as in the initial study: cross-file calls from top-level untyped functions, one caller per unique callee, SHA-256 ranking based only on `repo_without_types`. Take the first 120 cases across these repositories. The first six are a technical smoke set; the remaining 114 are the scored holdout. No selection by observed prediction or reference.
- Arm A: caller function, import statement, and target symbol. Arm B: the same plus deterministic `return_memory_v1` (at most 1,000 characters: decorators, return/yield expressions, relevant assignments, or the absence of an explicit return). Both use `gpt-5.4-mini` at temperature 0, one independent call per arm, no retries.
- Prediction validity and token usage are saved for every attempt. No re-prompts, manual corrections, or case substitutions.

## Primary analysis

After both arms are frozen, extract the typed `original_repo` copies. Only cases with a unique annotated top-level reference function are evaluable. Use the existing `score.py` strict AST-normalized return-type equality, including its exact two-sided McNemar test. Report all denominators and missing-reference reasons. The replication is positive only if at least 80 held-out cases are evaluable, Arm B has more exact matches than A, and p < 0.05. Also report the additional B input-token cost. The six smoke cases are excluded from the primary test.

This is an independent follow-up after an inconclusive first holdout, not an untouched first hypothesis test. Any positive result must be presented alongside the earlier null/inconclusive studies, with that sequencing made clear.
