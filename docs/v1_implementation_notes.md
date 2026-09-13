# V1 execution and interpretation notes

## Local inference and extraction

The primary model is `mlx-community/gemma-4-26b-a4b-it-4bit` at revision `0d77464eeb233a2da68ebf9d7dc4edaac7db956d`. After the initial attempt and two bounded format repairs, 178 of 180 extraction chunks passed validation. The remaining two chunks were processed successfully with the already available local `mlx-community/Qwen3.6-35B-A3B-4bit` snapshot `38740b847e4cb78f352aba30aa41c76e08e6eb46`. No remote LLM API was called.

The extractor emitted 2,658 validated fact occurrences. Stable-ID deduplication produced 2,632 stored semantic fact nodes, removing 26 repeated assertions with identical document, type, name, and supporting units. The final graph has 3,871 nodes and 8,150 edges. All fact nodes have source-unit and source-chunk provenance. Selected-unit coverage is 2,330/2,891 (80.6%); this measures source-unit selection, not semantic correctness or completeness.

## Pre-evaluation parser amendments

Two syntactic parsing issues were observed while answer generation was running and before benchmark answers or rationales were used for evaluation:

1. The model sometimes returned a known citation as `[C:3]` rather than `C:3`. The answer validator now removes optional surrounding display brackets and whitespace before checking the exact citation allowlist.
2. The model often omitted the auxiliary `insufficient_evidence` field or emitted a revised answer in a second complete JSON object. The answer parser now reads the last complete model-emitted answer object. An omitted auxiliary flag is stored as `null` (unreported); it is not inferred from the answer. Answers still require a nonempty answer and valid citations unless the model explicitly declares insufficient evidence. Responses that reach the output-token limit remain invalid and receive bounded retries.

These changes affect response parsing only. The graph, retrieval algorithm, retrieved question contexts, answer-generation prompt, model weights, and cached raw model responses were retained. No finance answer was edited by Codex. Existing complete generation batches were reused. The original and amended freeze records are retained under `artifacts/v1/freeze_history`, and the amendment explanations are included in `artifacts/v1/run_freeze.json`. This record should accompany the benchmark report so that the phrase “frozen V1” is not interpreted as implying that no pre-evaluation parser repair occurred.

## Interpretation of the benchmark

The final binary score is the external local model evaluator's score. Generation and grading use the same primary model weights with separate stateless prompts, so evaluator bias or correlated reasoning errors remain possible. Error diagnoses must not silently override the original judgments. The graph is a conservative graph of evidence-bound assertions rather than an executable financial rule engine. Hybrid graph/text accuracy alone does not establish improvement over a text-only baseline; that comparison is proposed for a bounded V2 experiment.
