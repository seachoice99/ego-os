# Epic 1: Evidence Research Engine

## Owner brief

A generic, reusable research capability that any Ego OS project can call on to build a versioned, evidence-backed dataset for a business question — not a one-off scraper built for Chip-Chip TV. Every fact it produces carries its source, when it was observed, how confident we are, and what it does *not* prove. Nothing is guessed and presented as fact; gaps stay visibly unknown. Bulk work runs as ordinary code (cheap, fast, reproducible); Claude/GPT are used only to plan the research and resolve genuinely ambiguous cases. Hard-coded refusals prevent it from ever bypassing CAPTCHAs, scraping paywalled content without an explicit grant, or harvesting personal data without your sign-off.

**Product impact:** this becomes the evidence backbone for Chip-Chip TV Licensing (Epic 4) and any future research-heavy initiative, without locking the codebase into that one vertical.

## Governing documents

- `memory/decisions/ADR-0008-evidence-research-engine-is-domain-agnostic.md`
- `architecture/014_EVIDENCE_RESEARCH_ENGINE.md`

## Risks

- **Legal/compliance**: even with hard collection boundaries, a specific research target could still be legally sensitive (e.g., a jurisdiction with strict scraping law). This Epic reduces but does not eliminate that risk — each *consuming* project remains responsible for its own targets.
- **Cost drift**: if disambiguation escalation to a model call isn't kept genuinely rare (bounded by the deduplication threshold), per-fact cost could grow unpredictably. Mitigated by ERE-02's explicit, documented threshold and by measuring escalation rate once real usage exists.
- **Scope creep into a real scraper toolkit**: the temptation to keep adding source-specific adapters inside the Engine itself must be resisted — a new adapter belongs to the consuming project's own tool wiring, not this Skill, unless it's genuinely general-purpose.

## Dependencies

- None on other epics. Epic 4 (Chip-Chip TV) depends on this epic reaching at least ERE-04 (Skill registered) before it can meaningfully use it for research; Epic 4's own tasks are written to not assume this exists yet.
- Depends on the existing Skill Registry / Tool Framework / Digital Asset precedent already shipped (ADR-0004, ADR-0005, ADR-0007) — no new infrastructure needed.

## Acceptance criteria (epic-level)

1. A second, unrelated consumer could invoke the Engine with its own Research Goal and Dataset Schema without any code change to `ego_os/evidence_research.py` or the Skill manifest.
2. Every Fact in a produced Dataset has non-null `source`/`observed_at` OR `status='unknown'` with a `limitations` reason — never neither.
3. No collection attempt bypasses CAPTCHA/bot protection, accesses paywalled content without an explicit owner-granted credential, or collects personal data without `owner_approved` — enforced by tests, not just documentation.
4. The Skill manifest's `trust.state` is `quarantined` (never `approved`) until a distinct, later Owner review action — this epic's tasks never self-approve.

## Execution order

`ERE-01 → {ERE-02, ERE-03} → ERE-04 → ERE-05 (Owner gate) → ERE-06`

ERE-02 and ERE-03 both depend only on ERE-01 and can run in either order (or, if ever parallelized, concurrently — they touch different concerns though the same file, so sequential is still recommended to avoid merge friction).

## Owner gates

- **ERE-05** (Collection tool): `risks: [external_infrastructure]`, `owner_approved: false` by default. Requires explicit Owner review and `owner_approved: true` before this task's `status` may become `ready` — this is the task that actually touches the outside world, even in its refusal-tested form.
- Skill approval itself (`trust.state: quarantined → approved`) is a *separate*, later Owner action per ADR-0005/`architecture/011`'s trust lifecycle — no task in this queue performs it.

## Tasks

`ERE-01.yaml` · `ERE-02.yaml` · `ERE-03.yaml` · `ERE-04.yaml` · `ERE-05.yaml` · `ERE-06.yaml` — all `status: blocked`, none executed as part of this planning session.
