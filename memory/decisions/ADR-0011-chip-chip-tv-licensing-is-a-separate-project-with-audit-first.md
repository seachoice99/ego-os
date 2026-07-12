# ADR-0011: Chip-Chip TV Licensing is a separate Ego OS Project; real business data never enters Git

## Status

Accepted by Owner on 2026-07-12, as part of the EGO OS OPERATIONAL EXPANSION initiative (Epic 4).

## Context

The Owner wants Ego OS to run licensing outreach for Chip-Chip TV (Цып-Цып ТВ) — rights/content cataloging, organization and contact research, outreach campaigns, negotiation and agreement tracking, revenue. Existing local spreadsheets/documents already contain some of this information, of unknown structure, quality, and overlap. The Owner explicitly required: audit first and change nothing; no bulk mailing; drafts-only outreach with per-email Owner approval; mandatory suppression/do-not-contact handling; no real credentials connected in this epic; old-table import is read-only into a temp DB first.

Two structural risks stand out beyond the epic's own explicit requirements, found while designing this ADR:

1. **This repository's Git remote is a real GitHub remote** (`https://github.com/seachoice99/ego-os.git`) whose public/private visibility has not been confirmed in this session. Real business data — contact emails, negotiation terms, revenue figures — must never depend on that visibility setting being correct; the design must be safe even if the repo were public.
2. **Chip-Chip TV licensing is a real, separate business concern from Ego OS's own product engineering** — its domain model, while it lives in the same codebase (per ADR-0001's "one digital company" framing, Ego OS running its own operations is itself a legitimate use), must not blur into `ego_os/`'s core product tables in a way that makes future product changes accidentally touch licensing data or vice versa.

## Decision

1. **A separate Project**, `projects/chip-chip-tv-licensing/`, per the existing Project pattern (`projects/ego-os/PROJECT.md`) — its own `PROJECT.md`, its own domain model doc, its own audit findings doc. Not folded into `projects/ego-os/`.
2. **Audit before any design commitment to real data.** The first task in this epic's queue (`CCTV-01`) locates existing local tables/documents, changes nothing, uploads nothing externally, and produces a structure/duplicate/conflict/quality report plus a mapping into the canonical domain model below — read-only, and its own findings doc contains no bulk copy of the source data, only structural description (field names, row-count-shaped statistics, example *categories* of conflict) so the findings doc itself is safe to commit even before repo visibility is confirmed.
3. **Real business data lives only in the local SQLite database, never in Git.** Every table in the domain model below (`Organizations`, `Contacts`, `Messages`, `Agreements`, `Revenue`, etc.) is additive SQLite, matching `ego_os/*.db`'s existing `.gitignore` exclusion — exactly the same pattern already governing the main Ego OS database. No task in this epic ever writes real contact names, emails, negotiation terms, or revenue figures into a file that gets committed. Committed artifacts describe *schema and process*, never *content*.
4. **Old-table import is read-only into a temporary, non-production database first** (a throwaway SQLite file, not `ego_os/ego_os.db`), inspected and validated before any decision to promote data into the real Chip-Chip TV tables — matching the Owner's explicit "импорт... сначала read-only и в temp DB" requirement. Promotion into production tables is a distinct, later, explicitly Owner-reviewed task, not implied by this ADR.
5. **Chip-Chip TV's "Research Evidence" is Epic 1's Evidence Research Engine, not a parallel implementation.** Rather than a bespoke evidence table, this Project supplies its own `ResearchGoal`/`DatasetSchema` to the domain-agnostic Engine from Epic 1 — this is the real, working proof of Epic 1's own "a second consumer with no code fork" acceptance criterion, not just an aspiration.
6. **Outreach is drafts-only, with a mandatory suppression check before a draft is even created, and per-email Owner approval before send.** A `Message` cannot exist in a `sent` state without a prior `approved` state carrying `approved_by`/`approved_at`. `do_not_contact` is checked at both the `Organization` and `Contact` level before any `Message` draft is generated; a suppressed contact/organization never gets a draft, not merely a blocked send.
7. **No real credentials, no real sending, in this epic.** The Timeweb SMTP adapter and reply-ingestion adapter (`architecture/017`) are designed and stubbed with a mock transport only. Any real `.env` entry, real send, or real IMAP poll against a live mailbox is explicitly out of scope and requires a distinct future Owner decision — this ADR does not authorize it.
8. **Secrets, when eventually configured, are server-side environment variables only** — matching `OWNER_USERNAME`/`OWNER_PASSWORD`/`OPENROUTER_API_KEY`'s existing pattern in `.env` (gitignored). No secret is ever a database column, a committed file, or a hardcoded default.

## Consequences

- The epic delivers real value (a working, evidence-backed pipeline through Negotiations) without ever putting real business data or credentials at risk from a Git-history leak, a public-repo misconfiguration, or an accidental bulk send.
- Slower initial value: outreach cannot actually send anything until a distinct, later Owner decision connects real Timeweb credentials — deliberate, matching the Owner's own "drafts-only first" sequencing.
- The temp-DB-first import step adds friction to using historical data, in exchange for never corrupting or duplicating-into the production Chip-Chip TV tables from an unvalidated source.
- Reusing Epic 1's Evidence Research Engine here creates a real, load-bearing dependency: if Epic 1's Engine has a design gap, Chip-Chip TV's research quality inherits it directly. This is treated as acceptable and even desirable — it is the mechanism by which Epic 1's domain-agnosticism claim gets tested against something real, rather than staying an untested assertion.
