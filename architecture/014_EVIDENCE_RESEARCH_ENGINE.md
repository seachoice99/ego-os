# Evidence Research Engine: domain model and Skill contract

Implements ADR-0008. Domain-agnostic by construction — no field, table, or prompt template here names a specific vertical (Chip-Chip TV or otherwise). A consuming Project supplies a Research Goal and a Dataset Schema at invocation time.

## Domain model

All tables are additive (`CREATE TABLE IF NOT EXISTS`), matching the Digital Asset model's own precedent (`architecture/013`). No table here is ever bulk-deleted; corrections are new rows or `superseded_by` links, never in-place overwrites of a Fact's evidentiary content.

```text
ResearchGoal
  id, question, target_entity_classes, evidence_classes_needed,
  out_of_scope, created_by, created_at, status

DatasetSchema           -- versioned; a schema change is a NEW version, never a mutation
  id, goal_id, version, fields (json), entity_types (json), created_at

Dataset
  id, schema_id, version, status (draft|active|superseded), created_at

Source
  id, url_or_reference, source_type (web|document|api|manual),
  retrieved_at, retrieval_method, access_basis (public|licensed|owner_granted)

Fact
  id, dataset_id, entity_ref, field, value, source_id,
  observed_at, confidence (0.0-1.0, documented scale -- see below),
  limitations (text, required), status (verified|unknown|disputed),
  superseded_by (nullable fact id)

DuplicateCluster
  id, fact_ids (json), resolution (merged|kept_distinct|unresolved),
  decided_by (code|model|owner), reason

CollectionRun
  id, goal_id, sources_targeted (json), sources_collected (json),
  started_at, finished_at, tool_used, errors (json)

NormalizationPass
  id, collection_run_id, raw_count, normalized_count, schema_version, errors (json)

DeduplicationPass
  id, normalization_pass_id, clusters_found, merges_applied, unresolved_count

AnalyticsView            -- derived only; never itself a source of new Facts (no circular evidence)
  id, dataset_id, definition, computed_at
```

### Confidence scale (must be documented, never implicit)

| Value | Meaning |
|---|---|
| 1.0 | Directly stated by a primary source, corroborated by a second independent source |
| 0.75 | Directly stated by a single primary source, uncorroborated |
| 0.5 | Reasonably inferred from a primary source by deterministic logic (e.g., domain WHOIS → likely operating entity) |
| 0.25 | Model-disambiguated from ambiguous/conflicting sources — always paired with a `limitations` note explaining the ambiguity |
| — | `status: unknown` — no numeric confidence; the gap and its reason are recorded, never silently omitted |

## Pipeline stages

1. **Collection** — deterministic fetch/scan code, governed by the Tool policy's hard boundaries (ADR-0008 §6). Produces a `CollectionRun` plus raw, unprocessed source captures.
2. **Normalization** — deterministic field mapping/cleanup into the target `DatasetSchema`. Produces a `NormalizationPass`.
3. **Deduplication** — deterministic fuzzy-match clustering against an explicit, documented threshold; only genuinely ambiguous clusters escalate to a bounded model disambiguation call. Produces a `DeduplicationPass` and `DuplicateCluster` records.
4. **Evidence Attribution** — the point at which a normalized, deduplicated record becomes a full `Fact` with every provenance field populated. Not a separate table — this is the Fact record's own completeness contract.
5. **Analytics** — read-only aggregation over `Fact`/`Dataset`. Never writes a new Fact; a discovery made during analytics that warrants a new Fact must go back through Collection/Normalization/Attribution like any other, so provenance is never skipped.

## Skill manifest (per `architecture/011`)

```yaml
schema_version: "1.0"
id: evidence_research_engine
version: "0.1.0"
name: Evidence Research Engine
description: Plans and executes goal-driven, provenance-complete evidence research producing a versioned Dataset. Domain-agnostic -- the caller supplies the Research Goal and Dataset Schema.
origin: { type: internal, source: ego-os, author: FiveSeven, license: proprietary }
trust: { state: quarantined, approved_by: null }   # NOT approved until ERE-04's Owner review
compatibility: { ego_os: ">=0.5,<1.0", manifest_schema: "1.x" }
entrypoint: { type: instructions, path: SKILL.md }
requirements:
  model_capabilities: [planning, disambiguation]
  tools: [web_fetch, document_parse, dataset_store]
  permissions: [read_project_context, network_fetch_public]
  network: outbound_public_only
  filesystem: dataset_store_scoped
contracts:
  input_schema: schemas/research_goal.json
  output_schema: schemas/dataset_version.json
lifecycle: { state: active }
```

Deliberately absent from `requirements.permissions`: any bot-protection bypass, any authenticated-scrape grant, any personal-data-collection grant. A future need for a specific licensed/authenticated source is a separate, explicit, Owner-approved permission — never implied by this manifest.

## Vertical task sequence

See `tasks/queue/ERE-*.yaml`. Order: ERE-01 → ERE-02 → ERE-03 → ERE-04 → ERE-05 (Owner gate) → ERE-06.
