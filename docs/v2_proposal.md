# Bounded V2 Proposal

This is a proposal, not an implemented second version. V1's graph, predictions, and binary judgments remain unchanged.

## Evidence from the V1 evaluation

V1 scored 108/120 (90.0%) with a local LLM judge. Numerical calculation scored 17/24 (70.8%), while cross-product questions scored 38/40 (95.0%). Annotated-document recall averaged 96.8%; all annotated documents were retrieved for 112/120 questions. The 12 failures include repeated denominator omissions (QA048, QA049, QA062), a month-offset error (QA015), missed extrema calculations (QA050, QA063), conditional interest-rate aggregation (QA036), a procedure/actor mix-up (QA035), exception selection (QA073, QA076), deadline ordering (QA100), and temporal eligibility scope (QA112).

These observations support improving computation and rule application before investing in a larger retrieval stack. Retrieval and extraction are not proven perfect; the benchmark and the same-model judge have limited coverage. A causal attribution requires controlled ablations.

## Priority 1: Evidence-linked calculation plans

Have the local LLM produce a typed calculation plan with source IDs for each operand, the selected rule, the operation, the output unit, and any rounding instruction. Validate the plan and execute only an allowlisted set of operations using Decimal and calendar arithmetic. Avoid arbitrary code execution. Return the plan and the result to the answer model for explanation.

The initial operation set should be small: addition, subtraction, multiplication, division, min/max selection, adding calendar months, and sorting relative deadlines. Check that every required operand is present. For an installment-delay formula, a numerator without its contract-month denominator must fail plan validation. Test unit conversion and truncation separately from rule selection.

## Priority 2: Small ontology extensions

Keep the V1 provenance model. Extend the English schema only where the observed failures motivate explicit representation; preserve Korean instance labels and original source text.

| Proposed node | Definition | Required attributes |
|---|---|---|
| Quantity | A sourced numeric value with an explicit original-language unit and bound semantics. | `value`, `unit_text`, `bound_kind`, `source_unit_ids`, `raw_text` |
| CalculationRule | A sourced operation and its required operand roles, with optional rounding rules. | `operation`, `operand_roles`, `output_unit_text`, `source_unit_ids` |
| TemporalScope | The interval or relative-date anchor over which a condition must hold. | `anchor_text`, `duration_text`, `boundary_text`, `source_unit_ids` |
| ConditionGroup | An explicitly represented conjunction/disjunction with scope shared by its child conditions. | `operator`, `source_unit_ids` |
| Exception | A sourced exception to an identified rule, including its applicability conditions. | `name`, `source_unit_ids` |

Proposed edges are HAS_QUANTITY, USES_OPERAND, HAS_TEMPORAL_SCOPE, ALL_OF/ANY_OF, APPLIES_WHEN, and EXCEPT_WHEN. An explicit OVERRIDES edge should be added only when source-supported precedence exists; do not infer legal precedence solely from document titles. If precedence is unresolved, expose the conflict.

QA112 motivates applying the one-year temporal window to the complete eligibility condition, not just one side of an OR. QA073 and QA076 motivate connecting exceptions to the rule they qualify. QA035 suggests a later optional ProcessStep/Actor extension, but one observed procedure error does not justify a large process ontology in the first V2 increment.

## Priority 3: More concise evidence context

V1 can emit differently named facts with the same source-unit set. Keep the graph's separate labels where useful, but present identical evidence once to the answer model. Group related rules, conditions, and exceptions together and reserve space for the governing special term. Retrieve at paragraph/table-row level with explicit footnote expansion instead of repeatedly including large overlapping chunks.

Measure the effect before introducing embeddings or a new graph database. A smaller context may improve both latency and rule discrimination, but this remains a hypothesis until tested.

## Evaluation plan and stop rule

1. Freeze a new `artifacts/v2` directory and a held-out or newly authored set of finance questions before implementing improvements.
2. Implement the calculator and the smallest needed schema additions as one bounded V2 change set.
3. Compare V1 and V2 using the same 120-item benchmark plus the held-out set. Include graph-only, hybrid, and text-only retrieval ablations to measure the graph's contribution.
4. Use an independent local judge and a small human-adjudicated sample. Specifically audit numerical answers, exception handling, and any evaluator disagreements. The V1 score remains the original model-judged score.
5. Report accuracy, per-stage errors, source coverage, latency, generation failures, and costs once. Stop and review the results rather than launching automatic recursive optimization.

A remote LLM API is a separate option only after local alternatives have been assessed and explicit user permission has been obtained. No remote API or V2 run was performed in V1.
