# ADR-0008: Evidence Research Engine is a domain-agnostic Skill, not a Chip-Chip TV feature

## Status

Accepted by Owner on 2026-07-12, as part of the EGO OS OPERATIONAL EXPANSION initiative (Epic 1).

## Context

Ego OS needs to run evidence-based research for a variety of business tasks — market research, competitive analysis, licensing-outreach evidence, sales intelligence. The first concrete, named consumer is Chip-Chip TV Licensing (Epic 4 of this same initiative), but the Owner explicitly required this capability NOT be built as a one-off for that project: "не привязывать к Цып-Цып ТВ или рассылке."

Per ADR-0002 (employees are competence containers) and the Skill/Capability architecture (`architecture/008`, `010`, `011`, `012`), reusable capabilities belong in the Skill Registry, not hardcoded into one project or employee. Research-style work in this codebase so far (the Researcher employee, the Skills-and-Capability-Management tasks SR-01..04) has been ad hoc: no standard shape for what a "researched fact" is, no separation between what a model asserts and what is independently verifiable, no dataset versioning, no explicit collection boundaries.

## Decision

Introduce the **Evidence Research Engine** as a Skill (`skills/registry/evidence_research_engine/`, per `architecture/011`'s manifest spec), with a supporting domain model (`architecture/014`), that any Employee or Project can invoke for a business research goal, producing a versioned Evidence Dataset. Nothing in the Engine's own logic, schema, or prompts names Chip-Chip TV, TV licensing, or any other specific vertical.

Principles this decision commits to:

1. **Goal and schema first.** Every invocation starts with an explicit, structured Research Goal (question, target entity classes, evidence classes needed, out-of-scope) and a Dataset Schema designed for that goal *before* any collection happens. The Engine refuses to "just start scraping" with no schema.
2. **Pipeline stages are separated and independently inspectable**: Collection → Normalization → Deduplication → Evidence Attribution → Analytics. Each stage's output is its own durable, versioned artifact — a failure or dispute in one stage never requires blindly rerunning the whole pipeline.
3. **Model use is bounded to planning and disambiguation.** Claude/GPT plan the research (goal decomposition, source-selection strategy, schema design) and resolve genuinely ambiguous cases ("is this the same organization under two names?"). Bulk, repeatable operations — fetching, parsing, hashing, matching, confidence scoring — run as deterministic code, never a per-item model call. This bounds cost and keeps the pipeline reproducible and auditable.
4. **Every fact is provenance-complete.** A Fact record always carries `source`, `observed_at` (when the source was retrieved, not when analysis happened), `confidence` (an explicit, documented scale, never a vague unlabeled "high/medium/low"), and `limitations` (what this fact does *not* establish). A fact with unknown provenance cannot enter a Dataset.
5. **Unknown stays unknown.** The Engine never backfills a missing fact with a model guess presented as fact. A gap is recorded as `status: unknown` with a reason — never silently omitted, never silently inferred without a flag.
6. **Hard collection boundaries**, enforced at the Skill's `requirements.permissions` / Tool policy layer (`architecture/010`'s Gate Control), not just prose: no bypassing bot protection or CAPTCHA; no accessing paywalled/authenticated content without an explicit, separately Owner-approved credential grant; no collecting personal data beyond what the researched entity has already, intentionally made public for a business purpose (no scraping personal social profiles, no aggregating private contact info) without an explicit `owner_approved` risk record.
7. **Domain-agnostic by construction.** Chip-Chip TV (Epic 4) is the Engine's first *consumer*, configured entirely through goal/schema parameters at invocation time — never a fork, never a special code path.

## Consequences

- A real test of "did we actually build this domain-agnostic" is a *second* real consumer reusing the same Skill without a code fork — not just a design claim in this ADR.
- Adds real complexity: five distinct pipeline stages instead of one "do research" black box, each needing its own storage/versioning. Deliberate — an inspectable pipeline was chosen over a single opaque step for both auditability and cost control.
- Legal/compliance exposure from indiscriminate scraping is structurally reduced by the hard collection boundaries, but this ADR does not itself constitute legal review of any specific collection activity — a consuming Project (e.g., Epic 4) remains responsible for confirming its own specific sources/targets are legally collectible for its purpose.
- Model cost is bounded because bulk operations never re-invoke a model per item; the tradeoff is more deterministic code to write and maintain per pipeline stage.
- Review this decision if a future consumer genuinely needs collection behavior the hard boundaries in principle 6 cannot express (e.g., a legitimately licensed, authenticated data source) — that should extend the permission model explicitly, never bypass it silently.
