# Error-to-context retrieval: first experiment

The implementation contract, evaluation rules, and agent handoff prompt are in [the experiment spec](experiments/error_to_context/EXPERIMENT_SPEC.md).

## Research question

When `mypy` reports a type error in an LLM-annotated Python repository, does showing the model the relevant definition from another file improve a single correction attempt over showing the error alone?

This is a small experiment on top of TypyBench. TypyBench supplies stripped repositories, typed reference repositories, and evaluation code. Its published repository does **not** include a type-prediction agent or an iterative correction loop, so those pieces must be added.

## Current setup

- Upstream: `https://github.com/typybench/typybench`, cloned at commit `51feed13381f6bd027caad1f5bf7c4de798bc6a5`.
- Python 3.12 virtual environment: `.venv`; package installed in editable mode, with `mypy==1.11.1`.
- Docker is installed and its daemon is reachable. The official evaluator builds one image per benchmark repository.
- Inference will use `gpt-5.4-mini` through the OpenAI-compatible endpoint `https://llm.codemate.ai/v1`, with the same fixed settings in both arms. No local model is required.
- The benchmark archive is stored at `/home/too_geeky/research/typybenchdata.archive`, outside Git. The `flask` dev-set repository, split metadata, and dataset README are extracted to `/home/too_geeky/research/typybenchdata`.
- The API key must be provided at runtime through `CODEMATE_API_KEY`; never commit it, put it in a prompt, or include it in result files. Use `CODEMATE_BASE_URL` and `CODEMATE_MODEL` for the endpoint and model ID.

## Scope and data

1. Pilot on `flask` from the dev split. If its baseline yields fewer than 20 eligible errors, report the smaller set or choose an additional dev repository before comparing methods; do not select cases based on treatment outcomes.
2. Start each run from the same copy of `repo_without_types`. Keep `original_repo` inaccessible to prompts and retrieval; use it only for scoring.
3. Generate initial annotations once with `gpt-5.4-mini` via the cloud endpoint. Save the predicted repository and the exact prompt/model settings. This snapshot is the shared starting point for all correction arms.
4. Run pinned `mypy` on that snapshot. Consider only `arg-type`, `assignment`, and `attr-defined` errors for the first study. Select the first 20 resolvable errors in sorted file/line order, before seeing correction outcomes.

## One-round comparison

For each selected error, reset to the same baseline snapshot and ask the same model for one minimal type-annotation correction:

| Arm | Information supplied to the model |
| --- | --- |
| A: error only | The error, affected source line, and fixed local context window. |
| B: error plus definition | All of A, plus one referenced function/class/type definition found in the stripped repository. |

Find the referenced symbol with Python AST and import resolution. Use a fixed maximum of one definition and 300 retrieved tokens. If the symbol cannot be resolved unambiguously, mark the case ineligible rather than searching by arbitrary text. Record the file path and line range of every retrieved snippet. Never retrieve from `original_repo`, the scored output, or a previous model answer.

Apply only syntactically valid annotation changes. Run `mypy` after each correction. Record whether the target error disappears and whether new errors appear. Save the resulting repository for TypyBench's TypeSim and TypeCheck evaluation.

## Primary result

- **Clean correction rate:** target error disappears with no new `mypy` errors.
- Report A versus B on the same cases, including the raw count and paired difference.
- Secondary: exact type match, TypeSim, total `mypy` errors, input/output tokens, and elapsed time. Record token usage from the endpoint when available; otherwise mark it unavailable rather than estimating billed cost.
- Inspect every apparent win or regression to distinguish useful cross-file evidence from accidental prompt effects.

This is a pilot, so report counts and examples rather than claiming broad statistical generalization from one repository.

## Implementation order

1. Confirm the extracted `flask` data layout and verify that it belongs to the dev split. This is already extracted; keep the typed reference isolated from inference.
2. Add `experiments/error_to_context/` with a cloud inference client, baseline annotation runner, `mypy` diagnostic collector, AST definition retriever, one-round correction runner, and results writer. Keep the published TypyBench evaluator intact. The client should read its key from `CODEMATE_API_KEY`, default its base URL to `https://llm.codemate.ai/v1`, and request `gpt-5.4-mini` unless overridden.
3. Run a three-case smoke test. Check that the retrieved definition comes only from the stripped repository and that each arm starts from the same snapshot.
4. Run the fixed 20-case pilot and score both arms with TypyBench.
5. Write a short result note with the table, two concrete examples, and failure modes.

## Repository-specific cautions

- The README's example `run.py` commands omit the required `--data-path` argument. Supply the unpacked dataset path when building or evaluating.
- `src/typybench/helpers.py` runs `mypy` on temporary copies and later deletes them. The experiment runner should invoke `mypy` on its own stable predicted repository so diagnostics map to real source files.
- The published Dockerfile installs several Python versions and builds a separate image per repository. Begin with one repository; do not build all 50 images for the pilot.
- Docker execution and cloud API calls may need host access outside this shell's sandbox. Do not mistake a sandbox permission or network error for a benchmark failure.
