# Epic 4: Chip-Chip TV Licensing

## Owner brief

Builds Chip-Chip TV's licensing outreach pipeline (rights catalog, contact research, campaigns, negotiations, agreements, revenue) as its own Project inside Ego OS — but starts with an audit that touches nothing, and never sends a real email or connects a real credential without your explicit, later go-ahead. Real business data (contacts, terms, revenue) lives only in a local database file that's never part of Git, exactly like Ego OS's own database already works. It reuses Epic 1's research engine rather than building a second one, which is also the real test that Epic 1 was actually built generic.

**Product impact:** the first real revenue-facing capability in this initiative — but deliberately the slowest to reach "can actually send an email," by design.

## Governing documents

- `memory/decisions/ADR-0011-chip-chip-tv-licensing-is-a-separate-project-with-audit-first.md`
- `projects/chip-chip-tv-licensing/PROJECT.md`
- `projects/chip-chip-tv-licensing/DOMAIN_MODEL.md`
- `projects/chip-chip-tv-licensing/OUTREACH_ADAPTER_DESIGN.md`

## Risks

- **Repo visibility unconfirmed.** Whether `github.com/seachoice99/ego-os` is public or private was not confirmed in this session. The domain model is designed to be safe either way (real data never committed), but this should be explicitly confirmed before `CCTV-01` runs — noted as an open item in `PROJECT.md`.
- **Audit scope ambiguity.** `CCTV-01` needs to know *where* the existing local files actually live — the task prompt asks rather than guesses/scans broadly, but this means it may need a quick human answer before it can proceed at all.
- **Real-send authorization is a distinct future decision.** Every adapter task (`CCTV-05`/`06`) ships behind a mock transport only. Reaching an actually-working send/ingest pipeline requires a separate, later Owner decision to connect real credentials — this epic's queue does not build toward that as an implicit next step; it stops deliberately short.
- **Data-quality unknowns.** Until `CCTV-01`'s findings exist, the domain model's shape is a reasoned proposal, not a validated fit — `CCTV-02` is explicitly permitted (and required) to note and apply corrections the real audit surfaces.

## Dependencies

- Hard dependency on Epic 1 (`ERE-01`, `ERE-02`, `ERE-03`) for `CCTV-07`'s integration slice — Chip-Chip TV's research layer is Epic 1's Engine, not a parallel build.
- No dependency on Epic 2 or Epic 3.
- Internal: `CCTV-01` gates everything; `CCTV-02` gates `03`/`04`/`08`; `03` gates `05`/`06`; `07` is the capstone depending on nearly everything.

## Acceptance criteria (epic-level)

1. `CCTV-01`'s findings doc contains no real contact/negotiation/revenue content — structural description only.
2. `ego_os/cctv.db` never appears in `git status` after any task in this epic runs.
3. No `cctv_messages` row ever reaches `sent` without a prior `approved` state carrying `approved_by`/`approved_at`.
4. A suppressed (`do_not_contact`) contact or organization never gets a drafted message — zero rows, not a blocked-status row.
5. `smtplib`/`imaplib` each appear in exactly one non-test module in this codebase (statically enforced).
6. `CCTV-07`'s integration slice proves Epic 1's Evidence Research Engine works for a second, real (if fictional-fixture) consumer with no code fork.

## Execution order

`CCTV-01 → CCTV-02 → {CCTV-03 → {CCTV-05, CCTV-06}, CCTV-04, CCTV-08} → CCTV-07`

`CCTV-07` additionally depends on Epic 1's `ERE-01/02/03`.

## Owner gates

Every task in this epic defaults to `status: "blocked"` and `owner_approved: false` — none map cleanly onto the existing five `OWNER_ONLY` risk categories (`destructive_data`/`irreversible_migration`/`payments`/`secrets`/`external_infrastructure`), since this Project handles real third-party personal/business data, a category the current risk taxonomy doesn't yet name explicitly. Given that gap, `status: "blocked"` (requiring an explicit human promotion to `ready`, task by task) is this epic's actual enforcement mechanism, not the `owner_approved` flag alone — reviewed manually before any task in this queue runs. `CCTV-01` in particular should not be promoted to `ready` until the repo-visibility question above is answered.

## Tasks

`CCTV-01.yaml` · `CCTV-02.yaml` · `CCTV-03.yaml` · `CCTV-04.yaml` · `CCTV-05.yaml` · `CCTV-06.yaml` · `CCTV-07.yaml` · `CCTV-08.yaml` — all `status: blocked`, none executed as part of this planning session.
