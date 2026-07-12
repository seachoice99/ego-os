# Project: Ego OS Operational Expansion

## Status

Planning complete (2026-07-12). No implementation task in any epic below has been executed — every `tasks/queue/*.yaml` this Project references is `status: "blocked"`.

## Goal

Four independent epics, each addressing a distinct operational need identified after RUNNER-CONTROL-UI shipped: a reusable research capability, safe visibility into the runner from Ego OS itself, a vendor-neutral usage policy, and a real revenue-facing licensing pipeline for Chip-Chip TV.

## Epics

| Epic | Brief | ADR | Domain doc |
|---|---|---|---|
| 1 — Evidence Research Engine | `EPIC-1-EVIDENCE-RESEARCH-ENGINE.md` | ADR-0008 | `architecture/014_EVIDENCE_RESEARCH_ENGINE.md` |
| 2 — Runner Integration | `EPIC-2-RUNNER-INTEGRATION.md` | ADR-0009 | `architecture/015_RUNNER_OPERATIONS_INTEGRATION.md` |
| 3 — Usage Optimization | `EPIC-3-USAGE-OPTIMIZATION.md` | ADR-0010 | `architecture/016_USAGE_OPTIMIZATION_POLICY.md` |
| 4 — Chip-Chip TV Licensing | `EPIC-4-CHIP-CHIP-TV-LICENSING.md` | ADR-0011 | `projects/chip-chip-tv-licensing/DOMAIN_MODEL.md` |

## Cross-epic relationships

- **Epic 4 depends on Epic 1** (`CCTV-07` requires `ERE-01/02/03`) — this is intentional and is the real proof that Epic 1's Engine is domain-agnostic, not a Chip-Chip-TV-specific tool wearing a generic label.
- **Epic 2 and Epic 3 both touch the task-YAML schema** (`executor`/`preferred_model`/etc. from Epic 2; no new fields from Epic 3) but do not conflict — Epic 3's tasks never read or write Epic 2's new fields.
- **Epics 1, 2, and 3 have no dependency on Epic 4** — they can run in any order relative to it.
- No epic depends on another epic's ADR being *implemented*, only (in Epic 4's one case) on specific functions existing.

## Independent, safe starting points

Since the four epics don't block each other except where noted, any of the following are valid places to start:

- `ERE-01` (Epic 1) — no dependencies at all.
- `RCI-01` (Epic 2) — no dependencies at all, and the lowest-risk task in the whole initiative (pure documentation).
- `UOP-01` (Epic 3) — no dependencies at all.
- `CCTV-01` (Epic 4) — no dependencies, but needs a human answer for *where* the existing local files live, and the repo-visibility question resolved first (see Epic 4's brief).

## What this planning session did and did not do

Did: four ADRs (`ADR-0008`..`ADR-0011`), four architecture/domain documents, four epic briefs (this folder), a separate `projects/chip-chip-tv-licensing/` Project with its own domain model and outreach-adapter design, and 23 `tasks/queue/*.yaml` files (`ERE-01..06`, `RCI-01..05`, `UOP-01..04`, `CCTV-01..08`), every one `status: "blocked"`.

Did not: implement any of the 23 tasks, touch any file under `ego_os/`, `automation/`, or `skills/registry/` beyond what's listed above, or perform any production deploy.
