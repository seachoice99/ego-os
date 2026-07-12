# Project: Chip-Chip TV Licensing

## Status

Planning — audit not yet performed (as of 2026-07-12). No code in this Project has run.

## Goal

Run Chip-Chip TV's (Цып-Цып ТВ) content/rights licensing outreach through Ego OS: catalog rights and content, research and track organizations/contacts, run evidence-backed outreach campaigns, and manage the resulting opportunities, negotiations, agreements, and revenue — safely, with drafts-only email until the Owner explicitly authorizes real sending.

## Governing documents

- `memory/decisions/ADR-0011-chip-chip-tv-licensing-is-a-separate-project-with-audit-first.md`
- `DOMAIN_MODEL.md` (this folder)
- `OUTREACH_ADAPTER_DESIGN.md` (this folder)
- Depends on Epic 1's Evidence Research Engine (`memory/decisions/ADR-0008-*`, `architecture/014_EVIDENCE_RESEARCH_ENGINE.md`) for its research/evidence layer — this Project does not implement its own parallel evidence system.

## Current focus

`CCTV-01`: locate and describe (never modify, never upload externally) existing local tables/documents about Chip-Chip TV licensing, so the domain model below can be validated against real historical structure before any data import.

## Key decisions

- A separate Project from `projects/ego-os/` — its own domain model, not folded into core Ego OS product tables.
- Real business data (contacts, negotiation terms, revenue) lives only in the local SQLite database, never in Git — same pattern already governing `ego_os/*.db`.
- Old-table import is read-only into a temporary database first; promotion into production tables is a distinct, later, Owner-reviewed step.
- Outreach is drafts-only with mandatory suppression checks and per-email Owner approval — no bulk mailing, no real send, in this epic's scope.
- No real SMTP/IMAP credentials are connected in this epic.

## Open item requiring Owner confirmation before CCTV-01 is marked `ready`

Whether `github.com/seachoice99/ego-os` is public or private has not been confirmed in this session. The domain model is designed to be safe either way (no real business data ever committed), but the Owner should confirm this explicitly before the audit task runs, since it affects how cautious even *structural* descriptions in `CCTV-01`'s findings doc need to be.

## Next milestone

Complete `CCTV-01` (audit) and review its findings before authorizing any schema-implementation task in this Project's queue.
