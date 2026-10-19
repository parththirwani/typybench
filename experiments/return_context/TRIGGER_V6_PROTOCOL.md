# Type-bearing source signals: second fresh-repository validation

## Policy fixed before inference

The v6 policy in `trigger_v6.py` keeps the v5 static-answer branch. For other
functions, it asks for bounded return memory only when untyped source contains
a yield, a cast, a direct constructor return, a return call rooted at an
imported module or class, or a directly returned variable assigned by a call
or explicit local annotation. Otherwise it uses the caller-only prompt. The
policy reads `repo_without_types` and does not use model predictions or typed
references. V2–v5 outcomes are development data; no v6 reference has been
opened or extracted while choosing this rule.

## Source-only cohort and calls

Use all 151 unique source-selected top-level callees with cross-file callers
from DB-GPT, phidata, taipy, vnpy, gpt-pilot, LLaMA-Factory, and Pillow. The
unchanged selector yields no eligible vnpy callees, leaving six contributing
repositories. None appeared in the previous return-context prediction runs.
Keep the 2,400-character caller cap, SHA-256 case ordering, and at-most-1,000-
character return memory. The selected case IDs and policy choices are frozen
before any cloud calls. The selected typed references are absent locally.

Run both A (caller only) and B (caller plus memory) independently for every
case using `gpt-5.4-mini`, temperature zero, at most one attempt per arm.
This requires 302 research calls. The deployed policy's cloud cost uses only
its chosen arm, or zero cloud tokens for a static answer. Save source/code,
selection, prompt, response, and usage hashes. Do not open any `original_repo`
files until the complete paired prediction set is frozen. Then extract only
selected typed `.py` files from the official dataset archive, verifying its
SHA-256 and refusing overwrites or unsafe paths.

## Primary gate

Score strict AST-normalized exact return annotation equality. Invalid model
answers count as incorrect. Report selected/evaluable denominators, missing
references, A/B/policy exact matches, static branch accuracy, two-sided exact
McNemar comparisons, model input and total tokens, and per-repository results.
The v6 result passes the substantial-saving gate only if at least 100 cases
are evaluable, the policy improves over A with case-level p < 0.05, and its
cloud input tokens are at least 20% below always-B. Report comparison with B
even if the gate passes; lack of a significant difference is not a formal
non-inferiority result. A failed gate stays a failure for this cohort.

This study tests a function-level return-type inference proxy. It does not
evaluate official TypyBench TypeSim/TypeCheck or coding-agent repair.
