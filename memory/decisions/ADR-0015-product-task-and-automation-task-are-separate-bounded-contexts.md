# ADR-0015: ProductTask and AutomationTask are separate bounded contexts

## Status

Accepted by Owner on 2026-07-13, as part of the 2026-07-13 architecture-correction pass.

## Context

This repository has always had two genuinely different kinds of "task," implemented in two genuinely different systems, but the shared English word "task" and overlapping documentation language have let the two blur together in prose (not in the actual schema, which was already accidentally correct):

- **The digital company's own work**, requested by the Owner in natural language, planned by the Orchestrator, staffed with an Employee, executed, QA'd, and delivered with a Report — persisted in `ego_os/store.py`'s `tasks` table (SQLite, `ego_os/ego_os.db`), driven by `ego_os/lifecycle.py` and scheduled by `ego_os/worker.py`. This is the subject of ADR-0001 ("digital company, not chat") and ADR-0014 (this pass's lifecycle ADR).
- **A technical instruction to autonomously change this repository itself** — implement a feature, fix a bug, deploy — persisted as one YAML file per task under `tasks/queue/*.yaml`, driven entirely by `automation/claude_task_runner.js` and its own state machine (`ready → in_progress → testing → deploying → done`, plus `blocked`/`waiting_for_limit`/`held`/etc., per `tasks/queue/README.md`), authorized by ADR-0006 (single-user autonomous development).

These already have different identifiers (`tasks.id` is an auto-increment integer; `tasks/queue/*.yaml`'s `id` is a human-chosen string like `DA-03`), different persistence (SQLite row vs. Git-tracked YAML file), different state machines (already fully distinct — no code path ever confuses one for the other), and different execution policies (a background worker thread calling a model provider vs. a spawned `claude`/`codex` CLI process editing files and pushing commits). No code-level conflation was found during discovery. The gap is purely that no document names this split explicitly, so a reader (or a future contributor) has no single place confirming these are deliberately separate, not an accidental inconsistency to "fix" by merging them.

## Decision

Adopt **ProductTask** and **AutomationTask** as the canonical names for these two bounded contexts, formally distinct along every axis the Owner specified:

| Axis | ProductTask | AutomationTask |
|---|---|---|
| Identifier/namespace | `tasks.id` (integer, SQLite auto-increment) | `tasks/queue/<ID>.yaml`'s own `id` (human-chosen string, e.g. `DA-03`) |
| Persistence | `ego_os/store.py`'s `tasks`/`reports`/`execution_events` tables | Git-tracked YAML file under `tasks/queue/` |
| State machine | ADR-0014's lifecycle (`intake → ... → delivered/failed/cancelled`, distinct `run_state` for scheduling) | `tasks/queue/README.md`'s runner state machine (`ready → in_progress → testing → deploying → done`, plus `blocked`/`waiting_for_limit`/`held`/`skipped`/etc.) |
| Execution policy | `ego_os/worker.py` background thread → `ego_os/lifecycle.py` → `ego_os/model_provider.py` (a model call producing text/artifacts) | `automation/claude_task_runner.js` → a spawned CLI process (Claude Code / Codex / OpenRouter-free per ADR-0012) that edits, tests, commits, pushes, and optionally deploys this repository |
| Reporting contract | ADR-0014's Report (`ego_os/store.py`'s `reports` table, built from `execution_events`) | The AutomationTask's own YAML `result` block, plus `automation/codex_usage.js`-style session logs — never the ProductTask Report schema |
| Authorization boundary | Owner Basic Auth + CSRF, per-route, per ADR-0001's product surface | ADR-0006's single-user autonomous development authority (commit/push/deploy within `allowed_paths`/`forbidden_paths`/`risks`/`owner_approved`) |

**Linkage is allowed only through explicit reference fields**, never by sharing an identifier or a table. Two linkage cases exist today or are introduced by this pass:
- An **EmployeeProvisioningTask** (ADR from Decision 7, tracked as an AutomationTask-shaped unit of work per its nature — it edits `company/employees/core/*.yaml`, a repository file) carries a reference field back to the ProductTask whose capability gap triggered it, and the ProductTask, once provisioning completes, carries a reference forward to the AutomationTask that provisioned its new specialist.
- Any future case where a ProductTask's execution needs a repository change must go through this same explicit-reference pattern (create/point at an AutomationTask), never by a ProductTask directly writing to `tasks/queue/*.yaml` or an AutomationTask directly writing to the `tasks`/`reports` SQLite tables.

## Consequences

- No renaming of existing tables/files is required — `ego_os/store.py`'s `tasks` table and `tasks/queue/*.yaml` already have separate, non-colliding real-world names (`ego_os` "task" vs. automation "task" respectively); this ADR gives the *concept* two names in documentation (ProductTask / AutomationTask) without forcing a code-level rename that would be a purely cosmetic, high-risk migration for zero behavior change.
- `architecture/000_SYSTEM_ARCHITECTURE.md`/`architecture/001_CORE_ENTITIES.md` (this pass's canonical architecture rewrite) name both entities explicitly as separate Runtime Records, each with its own authoritative owner.
- Documentation and prose (README/CLAUDE.md/AGENTS.md/workflows) that says just "task" without qualification should be read as ProductTask by default (matching the product-facing framing of ADR-0001) — automation-runner documentation already consistently says "AutomationTask"-shaped things via `tasks/queue/*.yaml` context, per `tasks/queue/README.md`'s own existing text.
- EmployeeProvisioningTask (Decision 7) is the first case requiring the explicit-reference linkage this ADR mandates — implemented per ADR-0014's scope for this pass (persisted record + linkage; not full unattended YAML generation, which remains a further, separately-scoped decision).
