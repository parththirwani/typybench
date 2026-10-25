# TypyBench experiments on cost-aware code memory

This repository contains the original [TypyBench](https://github.com/typybench/typybench) benchmark and experiments on when a language model should retrieve code memory during type inference.

The experiment asks a narrow question:

> When a model infers a function's return type, does the extra context from the callee justify its token cost?

The current results compare four policies on a repository-disjoint cohort of 151 functions. The static-analysis-plus-selective-memory policy matched the always-memory policy on exact return-type accuracy while using 33.71% fewer input tokens on the 116 functions with evaluable references.

## Four policies

The experiment uses the same `gpt-5.4-mini` model and the same bounded return-memory summary for the model-based arms.

1. **No memory.** The model receives the caller, import, and target symbol.
2. **Always memory.** The model receives the same prompt plus a summary of the callee's return expressions and related assignments.
3. **Source-signal trigger.** A deterministic rule chooses between no memory and memory. It requests memory when the summary contains an assignment, `yield`, `cast(`, or a constructor-style return.
4. **Static analysis plus selective memory.** A conservative AST rule answers directly when the source gives an unambiguous return type. For the remaining cases, a type-bearing source-signal rule chooses no memory or retrieved memory.

The trigger policies do not use a trained decision model. They make the memory decision from source code before the expensive model request. A static answer uses no cloud-model call.

## Results

The table below uses the v6 repository cohort: DB-GPT, phidata, taipy, gpt-pilot, LLaMA-Factory, and Pillow. The cohort contained 151 selected functions, of which 116 had a unique annotated reference.

| Policy | Exact matches / 116 | Accuracy | Input tokens / 151 | Total tokens | Input saving vs always memory |
| --- | ---: | ---: | ---: | ---: | ---: |
| No memory | 83 | 71.6% | 57,333 | 59,788 | 14.95% |
| Always memory | 87 | 75.0% | 67,413 | 69,119 | 0% |
| Source-signal trigger | 83 | 71.6% | 62,824 | 65,034 | 6.81% |
| Static analysis plus selective memory | 87 | 75.0% | 44,690 | 46,379 | 33.71% |

The static policy produced 41 direct answers. Twenty-eight of those had evaluable references, and all 28 were exact. It selected no memory for 77 functions and retrieved memory for 33.

The 33.71% saving is a deployment-cost estimate. During evaluation, the experiment ran both model arms for every case so that it could measure counterfactual accuracy and token use. Local AST parsing and source indexing are not included in the cloud-token totals.

The four-case accuracy gain over no memory was not statistically significant in this cohort, with a two-sided exact McNemar p-value of 0.344. Matching the always-memory total does not establish formal equivalence. The study also does not measure official TypyBench TypeSim or TypeCheck scores, wall-clock latency, or automated repair quality.

## Earlier source-signal result

An earlier repository-disjoint study used the source-signal trigger without the static-answer branch. It achieved 84 exact matches out of 110 evaluable functions, compared with 73 for no memory and 86 for always memory. It reduced input tokens by 5.76% against always memory. This result came from a different repository cohort and should not be pooled with the v6 numbers.

## Repository layout

```text
src/typybench/                       Original TypeSim and TypeCheck code
experiments/parameter_context/       Parameter-context experiments
experiments/return_context/          Return-context triggers and reports
experiments/error_to_context/        Type-error and repair experiments
```

The main reports are:

- [Four-policy comparison](experiments/return_context/four-policy-comparison-report.md)
- [v6 selective-memory report](experiments/return_context/decision-trigger-v6-report.md)
- [v4 source-signal report](experiments/return_context/decision-trigger-v4-report.md)
- [v6 protocol](experiments/return_context/trigger-v6-protocol.md)

## Reproducing the return-context analysis

The frozen v6 run stores its selection, predictions, reference extraction record, and scores under `experiments/return_context/runs/`. Run outputs are ignored by Git because they contain large generated artifacts. The source-only selector and scoring scripts are tracked in `experiments/return_context/`.

The four-policy table can be reproduced from the frozen v6 artifacts by applying the saved v3 source-signal rule to the v6 run:

```bash
python -c 'from pathlib import Path; from experiments.return_context.analyze_v5_development import analyze; from experiments.return_context.trigger_v3 import choose_arm; import json; print(json.dumps(analyze(Path("experiments/return_context/runs/trigger_v6_holdout_20261020"), chooser=choose_arm), indent=2))'
```

Run the unit tests with the pinned environment:

```bash
.venv/bin/python -m unittest discover -s experiments -p 'test_*.py'
```

The experiment suite currently passes 96 tests with the pinned dependencies. The system Python environment may report a mypy-version failure if it uses mypy 1.15 instead of the pinned 1.11.1.

## Original TypyBench benchmark

TypyBench contains 50 well-typed Python repositories for evaluating type inference in untyped Python repositories. It provides two metrics:

- **TypeSim**, which measures semantic similarity between predicted and reference types.
- **TypeCheck**, which measures type consistency across a repository.

Download the dataset from the [TypyBench dataset link](https://drive.google.com/file/d/1zeF658KElobutFseLgW1FyxXm-bVKlej/view?usp=sharing).

For the original benchmark, arrange predictions as follows:

```text
predictions/
  agents/
  appworld/
  AutoGPT/
```

Then run:

```bash
python3 run.py --pred-path ./predictions --num-workers 10
```

To evaluate one repository:

```bash
python3 run.py --pred-path ./predictions --num-workers 10 --repo agents
```

## Citation

If you use the original benchmark, cite:

```bibtex
@inproceedings{
  dong2025typybench,
  title={TypyBench: Evaluating {LLM} Type Inference for Untyped Python Repositories},
  author={Honghua Dong and Jiacheng Yang and Xun Deng and Yuhe Jiang and Gennady Pekhimenko and Xujie Si},
  booktitle={Forty-second International Conference on Machine Learning},
  year={2025},
  url={https://openreview.net/forum?id=xl9sv9vEDy}
}
```

## License

See the [LICENSE](LICENSE) file.
