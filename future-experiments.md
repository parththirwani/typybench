# Next experiments for cost-aware code memory

20 October 2026. These proposals follow the completed TypyBench-derived
return-type, parameter-type, and annotation-repair studies. They are plans, not
results. Freeze each protocol, selector, prompt, and decision rule before
opening typed references for its evaluation cohort.

## What the existing evidence leaves open

- On the v6 cohort, static analysis plus selective return memory matched
  always-memory's 87/116 exact answers and used 33.71% fewer cloud input tokens.
  The two policies traded three case-level wins each, so equal totals do not
  establish an acceptable accuracy loss. The gain over no memory was four
  cases and did not pass the declared accuracy test.
- A single observed cross-file call changed parameter accuracy from 48/90 to
  50/90, with exact McNemar p = 0.6875. Input tokens rose from 20,781 to
  48,315. The current call snippet is too costly for the measured gain.
- In the audited nine-site repair pilot, both arms made six clean corrections.
  The sample is too small, and `mypy` diagnostics often already state the
  expected and actual types.
- Current return and parameter scores use exact annotation strings. They do
  not measure official TypyBench TypeSim or TypeCheck, deployed latency, or
  whether an inferred type improves a complete repository.

## Available data and separation

The local extracted dataset includes the repositories used in prior studies.
The split file also lists several repositories that do not appear in the local
extraction or in the return-study reports, including `screenshot-to-code`,
`exo`, `TEN-Agent`, `lerobot`, and `unstract` in `test2`, and `AutoGPT` and
`mlc-llm` in `test1`. Check the full case manifests before calling any one of
these untouched. Extracting them from the existing archive, if present,
would add repositories but not a new source population. A genuinely external
replication should use repositories outside TypyBench, selected by a dated
source-only rule and with independently obtained type references.

Keep repositories, rather than functions alone, separate between development
and final evaluation. Never use typed `original_repo` content in selection,
retrieval, prompts, or policy fitting. Preserve missing-reference counts.

## 1. Validate the v6 policy on more repositories

**Question.** Does the fixed static-plus-selective policy retain a material
token saving while losing no more than an agreed amount of exact accuracy
against always memory?

Use the existing v6 rule and prompts without edits. Select new repositories
first, then all eligible cross-file return sites up to a declared per-repository
cap. Run both model arms once per site so the counterfactual is observed, and
replay the frozen policy. Aim for at least eight contributing repositories and
several hundred evaluable functions. Calculate the required sample size from
the declared accuracy-loss margin and expected paired discordance before
paying for inference. A 3 percentage-point margin is a concrete candidate,
but it must be agreed before the new results are seen.

The primary outcome is the paired difference in exact accuracy, policy minus
always memory, with a repository-aware confidence interval. Claim
non-inferiority only if its lower bound exceeds the negative margin. Require
at least 20% fewer input tokens as a separate cost gate. Report no-memory
accuracy, per-repository effects, missing references, actual request count,
token use, and wall time. Start with unused TypyBench repositories if the
archive supports them; reserve external repositories for a separate
replication. Do not pool old and new cohorts as though they were one untouched
test.

## 2. Find which return-memory content is useful

**Question.** Are return expressions, assignments, import-resolved call
targets, or full callee bodies responsible for helpful changes?

Use previously studied return cases for development. Build source-only memory
variants with the same token cap: return expressions only, return expressions
plus assignments, resolved signatures or definitions of called symbols, and
the existing summary. Add a length-matched irrelevant snippet control to
separate useful evidence from the effect of a longer prompt. Freeze the chosen
variants and test them on repository-disjoint cases. Keep the caller prompt,
model, generation settings, and output format fixed.

Measure exact accuracy, B-only and A-only wins, retrieved-token count,
latency, and answer changes by source pattern. Compare each variant with the
same no-memory arm. This experiment determines what a later selector should
choose, rather than merely whether it should retrieve anything.

## 3. Test a learned read decision against the simple rule

**Question.** Can a small decision model select the useful memory cases using
only information available before generation?

Train on saved paired outcomes from the earlier return cohorts. Inputs may
include AST return shape, import and call structure, summary length, and a
cheap first-pass uncertainty signal only if that first pass is charged to the
policy. Exclude typed references, correctness labels, and model answers from
the evaluation repositories. Freeze the fitted model and its cost threshold,
then compare it with no memory, always memory, the v3 source rule, and the v6
static-plus-selective rule on new repositories. If experiment 1 already uses
the remaining untouched TypyBench repositories, collect an external cohort
for this test.

Plot exact accuracy against total cloud tokens across fixed thresholds.
Predeclare one operating threshold and score it as the primary test; treat
the full curve as descriptive. Include selector compute and any probing calls
in the cost and latency accounting.

## 4. Improve parameter evidence before another call-retrieval test

**Question.** Does compact, diverse call-site evidence help parameter typing
more than one long caller snippet?

The existing single-call arm cost over twice as many input tokens as the
baseline and gained only two exact answers among 90 cases. On development
repositories, compare one compact argument expression, several distinct
cross-file call arguments under one fixed budget, and the current caller
snippet. Distinguish literal, constructor, variable, and ambiguous calls
before scoring. Include a length-matched unrelated-call control. Freeze a
single promising format and repeat it on repository-disjoint cases.

Use exact parameter accuracy as the primary measure, with semantic type
equivalence and added tokens as secondary measures. Report results by call
kind and by reference type complexity. An observed call can be narrower than
the declared parameter type, so manual review of discordant pairs remains
necessary.

## 5. Move from annotation proxies to repository and repair outcomes

**Question.** Do memory-assisted type choices reduce actual repository errors
or improve one-step automated repairs?

Create complete annotation baselines for a small set of new repositories.
For a repository-level type test, apply each policy's predictions to separate
copies of the same baseline and run the official TypyBench TypeSim and
TypeCheck evaluator. Record coverage and cases where interacting edits change
the outcome. For a repair test, freeze real failing diagnostics and paired
baseline copies, then compare the same correction prompt with and without one
resolved definition or verified prior repair. Sample errors for which the
diagnostic does not already disclose the needed cross-file type, while also
reporting how often that eligibility condition occurs in the full error pool.

Primary repair outcome: a valid edit removes the target diagnostic without
adding errors, and passes any relevant repository tests. Track regressions,
invalid edits, tokens, end-to-end latency, and attempts. A prior-repair memory
must come from an earlier verified repair in the same training repository;
prevent access to held-out fixes. This is the direct test of whether memory
helps an automated repair workflow, rather than only a type-prediction proxy.

## Recommended order

1. Run experiment 1 with the current policy. It addresses the strongest
   existing claim and needs the fewest design changes.
2. Use old cohorts to develop experiments 2 and 4, while preserving new
   repositories for their frozen tests.
3. Run experiment 3 only after defining its token and accuracy objective.
4. Invest in experiment 5 once a memory format has shown a repeatable gain.

For every study, save source selection, exclusions, prompt hashes, model
settings, usage, predictions, reference-access time, and paired case outcomes.
Use repository-aware intervals alongside case-level paired tests. Treat
changes to prompts or selectors after inspecting a cohort as development and
validate them on another cohort.
