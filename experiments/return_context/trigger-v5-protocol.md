# Selective memory with a static answer path: fresh-repository test

## Locked question and policy

Test whether a source-only three-way policy improves return-type accuracy over
no memory while using at least 15% fewer cloud input tokens than always adding
memory. The policy is fixed in `trigger_v5.py` and `explore_static_types.py`
before any typed reference for this cohort is extracted or any model call is
made. It chooses:

1. a free static type when the untyped target has no explicit return or yield
   and no `raise` or `assert`, or when a final return has one unambiguous type
   from literals, selected builtins, a direct constructor, or a local variable
   annotation;
2. otherwise, the unchanged v3 source-signal rule chooses A or B.

A is the caller/import/target prompt. B is the same prompt plus the bounded
return-behavior memory. The static branch makes no model call. Its local AST
inspection and memory construction are included in the method, but their CPU
cost is not counted as cloud tokens. No model output, typed reference, or
case outcome is used to choose the branch.

## Cohort and reference isolation

Use all 129 source-selected top-level callees with cross-file callers from
supervision, gpt4free, paper-qa, vllm, agents, and private-gpt. These six
repositories were absent from all prior return-context studies. They were
chosen from official TypyBench's stripped source archive. Use the unchanged
2,400-character caller limit and deterministic SHA-256 case ordering; keep
every selected case. The six `original_repo` directories are absent before
inference. Record selection, memory, policy action, code hashes, prompt hashes,
responses, usage, and a final row freeze. Only after freeze, extract selected
typed `.py` reference files from the official archive.

For auditability, run both A and B on every selected case using `gpt-5.4-mini`
at temperature zero, one call per arm with no retries. The policy's deployed
cost uses only its chosen model arm, or zero cloud tokens for a static answer.
The full paired run costs 258 research calls but gives counterfactual A/B
outcomes for each function. Failed or missing-usage calls prevent the freeze.

## Decision and reporting

The primary metric is strict AST-normalized exact equality to the original
return annotation, with invalid model outputs counted incorrect. Report all
selected and evaluable denominators, missing-reference reasons, static branch
coverage and precision, A/B/policy exact matches, two-sided exact McNemar
comparisons against A and B, input plus output tokens, and results by
repository. The substantial-saving gate passes only if at least 90 cases are
evaluable, the policy beats A with a case-level p < 0.05, and its cloud input
tokens are at least 15% below always-B. Also report whether policy accuracy
is within three exact matches of B, descriptively; this is not a formal
non-inferiority test. If the gate fails, report failure without tuning this
cohort's policy.

Previous v2, v3, and v4 runs informed this policy and are development data.
The result is a function-level return-type inference proxy, not an official
TypyBench TypeSim or TypeCheck score or evidence about automated repair.
