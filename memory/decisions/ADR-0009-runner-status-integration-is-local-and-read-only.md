# ADR-0009: Runner status surfaces in Ego OS Operations UI as local, read-only, non-proxied data

## Status

Accepted by Owner on 2026-07-12, as part of the EGO OS OPERATIONAL EXPANSION initiative (Epic 2).

## Context

RUNNER-CONTROL-UI shipped a local control server (`automation/control_server.js`, bound to `127.0.0.1` only, launched via `npm run runner-ui`) and dashboard for the autonomous task runner. The Owner wants runner/task status (including the split between Claude and Codex work, once Codex exists) visible from within Ego OS's own, Owner-authenticated Operations surface — but explicitly required: "не открывать управление runner публично" (never open runner control publicly) and "state-changing команды должны оставаться локальными или требовать отдельной безопасной архитектуры."

This is a genuine cross-trust-boundary question, and the honest first finding of this ADR's own threat-modeling is architectural, not just a permission rule: **the runner and control server run on the Owner's own local machine; production Ego OS (`os.fiveseven.ru`) runs on a separate VPS** (`DEPLOYMENT.md`). These are different machines with no assumed network path between them. "Ego OS Operations UI" reading runner status therefore cannot mean the production, internet-facing deployment reaching into `127.0.0.1:4756` on a machine it has no route to — that integration is not just risky, it is not even topologically available by default. Treating this as a simple "add an HTTP client" task would be a category error.

## Decision

The integration in this epic is **local Ego OS instance ↔ local control server, both on the Owner's own machine** — never production Ego OS. Concretely:

1. **Read-only status, nothing else, in this phase.** A local Ego OS instance (the same `uvicorn ego_os.main:app` the Owner already runs during development) gains a new, Owner-authenticated route group that reads the runner's own persisted state (`runner_state.json`, `events.ndjson`, `tasks/queue/*.yaml`) directly from disk, or makes `GET`-only requests to the local control server's existing read API. It never issues a `POST` to the control server, ever, from Ego OS's own backend.
2. **State-changing commands stay exactly where they already are.** The existing `npm run runner-ui` dashboard remains the *only* place Pause/Resume/Stop-after-stage/Emergency-stop can be issued. Ego OS's Operations UI may render a plain hyperlink to `http://127.0.0.1:4756` that the Owner's own browser opens directly — Ego OS's backend never proxies, forwards, or otherwise mediates a control-server command.
3. **Production Ego OS never integrates with the runner in this epic.** If a future need arises to see runner status from the public production UI, that crosses a real network trust boundary (local machine → internet-facing VPS) and requires its own ADR and threat model — explicitly out of scope here, not silently deferred by omission.
4. **New task-model fields are informational, not authority-granting**: `executor` (`claude`/`codex`/`auto`), `preferred_model`, `fallback_executor`, `context_budget`, `max_duration`, and a `usage` state block are added to the task YAML schema as optional fields (old tasks unaffected, matching TOKEN-EFFICIENCY-001's own precedent). Since no Codex executor exists yet, the runner **fails closed** on any `executor` value other than `claude`/`auto` — it refuses the task with a clear error rather than silently running it as Claude or silently ignoring the field.
5. **Usage data is shown only when genuinely available.** No estimated-and-presented-as-real numbers. `result.sessions[].prompt_approx_tokens` (already labeled "approx") is the only real signal today; "usage data not available" is a first-class, clearly labeled UI state.
6. **No screen scraping, ever.** Any data flowing from the control server into Ego OS's Operations UI comes through its existing JSON contract (files on disk or its `GET` API) — never by parsing rendered HTML or a screenshot.

## Consequences

- This delivers less immediate value than a "see runner status from anywhere" design would — the Owner must be at their own machine (or its local Ego OS instance) to see live runner status. This is the deliberately correct, safe tradeoff for this epic, not a stopgap to silently outgrow later.
- A future cross-machine status relay is explicitly named as a distinct, harder problem this epic does not solve — reviewing this ADR is the right first step before attempting it, not extending this epic's scope.
- Adding executor/model/budget fields ahead of an actual Codex integration is deliberate (schema-first) but creates a real, named risk: an unused field can drift from its intended meaning if Codex integration stalls indefinitely. Mitigated by the fail-closed rule in point 4, which makes an unimplemented `executor` value a hard error, not a silently-accepted no-op.
- `architecture/015_RUNNER_OPERATIONS_INTEGRATION.md` carries the full threat model this decision is based on.
