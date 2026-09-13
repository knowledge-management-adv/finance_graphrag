# Finance Document Ontology — Version 1.0

## Purpose and scope

This minimal, extensible property-graph ontology supports document-grounded question answering about financial products. Schema identifiers and this specification are English. Instance names, extracted labels, statements, conditions, values, and source text retain the language of the source (Korean in this corpus). English words already present in a product name are preserved. No translation is performed.

The ontology is designed from source documents and general finance-document structure, not benchmark answers, rationales, evidence, or question-specific rules. It represents documentary assertions rather than an independently verified current view of financial regulations. Conflicting document versions are retained; dates are never silently used to declare a rule current.

## Node types

| Type | Definition | Required attributes | Optional attributes |
|---|---|---|---|
| Source | One source-file occurrence in a product directory; preserves original location even when contents are duplicates. | `id`, `path`, `relative_path`, `sha256`, `product_name` | `file_mtime` |
| Document | A content-addressed document version, shared only when raw UTF-8 content is identical. | `id`, `sha256`, `title`, `text`, `source_count` | `date_mentions` (literal strings, not interpreted validity dates) |
| Chunk | A deterministic, bounded group of source units used for extraction and retrieval. | `id`, `document_id`, `ordinal`, `text`, `unit_ids`, `pages`, `headings` | — |
| Product | A product as identified by its source directory; directory distinctions such as installment method or legal-person eligibility remain distinct. | `id`, `name` | `aliases` (mechanical punctuation/spacing normalization only) |
| Organization | An explicitly mentioned organization. | `id`, `name` | — |
| Concept | A reusable, explicitly mentioned financial or operational concept. It is not a synonym dictionary or an inference. | `id`, `name` | — |
| Rule | An asserted policy, calculation, product attribute, definition, or procedure. | Fact attributes below | — |
| Condition | A prerequisite, temporal trigger, eligibility criterion, or qualifying situation. | Fact attributes below | — |
| Requirement | An action or item that must be supplied or completed. | Fact attributes below | — |
| Benefit | An interest advantage, service advantage, subsidy, exemption, or entitlement. | Fact attributes below | — |
| Restriction | A prohibition, exclusion, limit, disqualification, or exception restricting applicability. | Fact attributes below | — |

The five fact types are specialized documentary assertions. `Rule` is the general fallback. A single evidentiary statement may combine a benefit and its condition; it is retained as a qualified fact rather than splitting the condition away and accidentally asserting an unconditional benefit. Exact numeric and temporal details remain in the statement. Executable arithmetic and normalized numeric operators are deliberately deferred.

### Fact attributes

- `id`: Stable hash of document ID, type, normalized name, and supporting unit IDs.
- `name`: A short Korean label supplied by the extraction LLM.
- `statement`: Verbatim normalized source-unit text selected by the LLM; this is assembled from the referenced units, not invented by the pipeline.
- `unit_ids`: Non-empty list of source units selected by the LLM.
- `document_id`: The unique source document version.
- `extraction_run`: Content-addressed generation record including model, prompt, and configuration identity.

Statements are evidence-bound textual assertions, not fully normalized subject–predicate–object facts. This intentionally conservative representation supports reliable first-version QA while keeping extension points for numeric values, scoped conditions, and explicit exceptions.

## Edge types

| Type | Source → Target | Meaning | Attributes |
|---|---|---|---|
| HAS_VERSION | Source → Document | This file occurrence contains this exact document version. | — |
| DESCRIBES | Source → Product | Directory membership associates this source with this product. This is structural scope, not an LLM assertion. | — |
| HAS_CHUNK | Document → Chunk | Document contains the ordered chunk. | `ordinal` |
| NEXT_CHUNK | Chunk → Chunk | The next chunk in the same document. | — |
| ASSERTS | Document → Fact | A document asserts the extracted fact. | — |
| SUPPORTED_BY | Fact → Chunk | The fact is supported by units included in this extraction chunk. | `unit_ids` |
| MENTIONS | Fact → Organization or Concept | A selected evidentiary statement explicitly mentions this entity. | `unit_ids` |

`Fact` in this table denotes Rule, Condition, Requirement, Benefit, or Restriction. Each MENTIONS edge is supported by its fact's evidence. No implicit entity relationship is promoted to a fact. Product-to-fact traversal is `Product ← DESCRIBES — Source — HAS_VERSION → Document — ASSERTS → Fact`.

## Source units and provenance

Source units are a persisted provenance table rather than additional graph nodes. A unit has `id`, `document_id`, `ordinal`, `text`, `heading`, `page`, `raw_start`, `raw_end`, and optionally `table_row`. Offsets refer to Unicode character positions in the stored original document, not bytes or normalized text. For HTML table rows, offsets cover the parent table because repeated header/rowspan values can originate in earlier rows; `table_row` identifies the selected logical row. Long units are split deterministically; each part keeps its parent raw span.

Every semantic fact must reference at least one valid unit and at least one containing chunk. Every entity must be linked to a supported fact. Source hashes and document text make evidence auditable even if the original files subsequently change. File modification times are ingestion metadata, not effective dates.

## Identity, validation, and versioning

Identifiers use SHA-256-derived stable IDs. Documents deduplicate by exact raw-content hash; sources never deduplicate across paths. Products deduplicate by their original directory names only. Entities merge by exact Unicode/whitespace-normalized spelling and type, with no fuzzy semantic merge. Facts from different documents remain separate, preserving disagreements and date distinctions.

The extractor must return only permitted types and existing unit IDs. Unsupported references and malformed outputs are rejected and retried at most twice. Entity names absent from the selected statement are rejected. Final graph validation checks edge endpoints, allowed edge signatures, source-to-document hashes, complete chunk extraction status, and evidence consistency. Failed chunks are visible and prevent a successful complete build.

## Rationale and tradeoffs

SQLite provides transactional persistence and indexed, explicit edge traversal without a running database server. The property graph is also exported as portable node/edge JSONL. Neo4j is a reasonable later deployment option for concurrent graph exploration, but it is not needed for this small first-version corpus.

Evidence-bound facts reduce hallucination and retain Korean financial terminology. Their cost is coarser semantic structure: exception precedence, conjunction/disjunction, date validity, units, and numerical comparisons are currently expressed in text. These limitations must be investigated after the full benchmark run, not patched with benchmark answer-specific extraction logic.

The retrieval stage may load source chunks through SUPPORTED_BY and NEXT_CHUNK edges. It must start from question-only lexical/entity matching, and it must return actual graph facts and their traversal provenance. Reading additional source text does not turn that text into a graph fact.

## Extension policy

After the first complete evaluation, consider adding typed Quantity, TemporalScope, ConditionGroup, and Exception nodes; explicit APPLIES_WHEN, EXCEPT_WHEN, and OVERRIDES relationships; curated entity aliases; and document-version precedence. Adopt only extensions supported by measured error analysis. Do not automatically rerun unlimited optimization cycles.
