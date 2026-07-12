# Runner Operations Integration: threat model and API contract

Implements ADR-0009. Read this before implementing any RCI-* task — the boundary rules here are the whole point of the epic, not incidental detail.

**2026-07-13 update:** the topology this document was written against has changed (the control server now runs co-located with Ego OS itself, per `automation/WINDOWS_AGENT_VERIFICATION.md`, not only on a separate machine the Owner's browser could reach directly), and the "Ego OS never POSTs to the control server" rule below (Elevation of Privilege row, and the "Forbidden, permanently" list) is **narrowly superseded by `ADR-0013`** for exactly the safe, loopback-only, Owner-authenticated local scenario ADR-0013 defines — every other row of the STRIDE table and the rest of this document's topology/threat analysis remains authoritative and unchanged. Read `ADR-0013` before assuming the "no POST, ever" language below is still the current rule.

## Topology (the finding that shapes everything else)

```text
Owner's local machine                       VPS (os.fiveseven.ru)
┌─────────────────────────────┐             ┌──────────────────────┐
│ automation/control_server.js │             │ production ego_os     │
│   127.0.0.1:4756  (loopback) │             │   (public, Owner Auth)│
│           ▲                  │             └──────────────────────┘
│           │ GET only          │              NO CONNECTION to the
│  local ego_os (dev instance) │              left side. Ever, in
│    (Owner Auth, same as prod)│              this epic's scope.
└─────────────────────────────┘
```

Production Ego OS has no code path to the control server in this epic. This is enforced by construction (no HTTP client to `127.0.0.1:4756` exists in any code path reachable from a production request), not by a runtime environment check that could be misconfigured.

## Threat model (STRIDE-lite, scoped to this integration)

| Threat | Assessment | Mitigation |
|---|---|---|
| **Spoofing** | No new surface — the local Ops routes require the same Owner Basic Auth as every other Ego OS route (`ego_os/auth.py`). An attacker who could spoof that already has broader access than this feature could add. | Reuse existing auth, no bypass route added. |
| **Tampering** | `runner_state.json`/`events.ndjson`/task YAMLs are plain files on local disk. The Ops read path must treat them as untrusted-ish input for *parsing* purposes. | Malformed JSON is caught and rendered as "unavailable," never crashes the route (matches `listTasks()`'s existing skip-and-warn behavior in `claude_task_runner.js`). |
| **Repudiation** | Not a new concern. | The control server's append-only event log already exists; this integration only reads it. |
| **Information Disclosure** | If raw log content is ever surfaced through Ego OS (not required by this epic's baseline scope), it must not leak secrets. | Reuse `runner_control.maskSecrets()` — never reimplement masking. |
| **Denial of Service** | Local file reads / local-only GET calls cannot be used to DoS anything beyond the Owner's own machine. | Out of scope for further hardening at this phase. |
| **Elevation of Privilege** | **The one real risk this epic exists to prevent.** Production Ego OS gaining *any* path — direct, proxied, or via a flippable feature flag — to the control server's `POST` routes would let a production-auth bypass become local process control. | No HTTP client to the control server exists anywhere in `ego_os/` outside the local-only Ops route group; that route group never issues `POST`. Enforced by RCI-05's static check (grep for `4756`/control-server references outside the intended module) plus a runtime assertion test. |

## API contract (what the local Ops routes may call)

Allowed:
- Direct filesystem reads of `runner_state.json`, `events.ndjson`, `tasks/queue/*.yaml` (same machine, same user).
- `GET http://127.0.0.1:4756/api/status`, `/api/tasks`, `/api/tasks/:id`, `/api/events` — read-only, already exist.

Forbidden, permanently, from `ego_os/`:
- Any `POST` to `127.0.0.1:4756/api/runner/*` or `/api/tasks/*/*`.
- Any code path that becomes reachable from a request Ego OS received over its own public listener (i.e., the Ops routes must be inert/return "unavailable" when the runner's local files don't exist — this is the natural behavior when Ego OS itself runs on the VPS, since the runner's state files simply aren't there).

## Task-model schema additions

```yaml
executor: claude            # claude | codex | auto -- see fail-closed rule below
preferred_model: null       # optional capability hint, not a vendor lock (matches models/MODEL_SELECTION_POLICY.md)
fallback_executor: null     # optional; same fail-closed rule applies once resolved
context_budget: null        # optional int, informational only in this epic (not causally enforced, matching token_budget's own honest precedent)
```

Per-stage wall-clock timing continues to use the existing `max_duration_minutes` field (TOKEN-EFFICIENCY-001) exclusively — this integration does not introduce a second, confusingly similar field for the same concept.

**Fail-closed executor rule:** `claude_task_runner.js` must refuse (not silently run, not silently ignore) any task whose `executor` is present and is neither `"claude"` nor `"auto"` — until a real Codex executor exists, `"codex"` is a valid *schema* value with no valid *runtime* path. This mirrors the auth fail-closed principle from RUNNER-CONTROL-UI: an unimplemented capability must produce a clear, loud failure, never a quiet no-op.

## Vertical task sequence

See `tasks/queue/RCI-*.yaml`. Order: `RCI-01 → RCI-02 → RCI-03 → RCI-04 → RCI-05`.
