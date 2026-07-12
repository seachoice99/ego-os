# ADR-0013: Safe local runner control from Ego OS supersedes ADR-0009/architecture-015's blanket POST prohibition

## Status

Accepted by Owner on 2026-07-13, as part of the 2026-07-13 architecture-correction pass. Resolves `architecture/018_ARCHITECTURE_CONTRADICTION_AUDIT_2026-07.md`'s C-01/C-02.

**Supersedes, narrowly:** `memory/decisions/ADR-0009-runner-status-integration-is-local-and-read-only.md`'s Decision points 1 and 2 (the "it never issues a POST ... ever" / "Ego OS's backend never proxies, forwards, or otherwise mediates a control-server command" clauses) and the matching prohibition in `architecture/015_RUNNER_OPERATIONS_INTEGRATION.md:38-40` ("Forbidden, permanently, from `ego_os/`: Any `POST` to `127.0.0.1:4756/api/runner/*` or `/api/tasks/*/*`"). Every other clause of ADR-0009 and `architecture/015` remains in force unchanged (read-only status data, no production access, no external host, Owner Auth, CSRF, the STRIDE threat model's other rows).

## Context

ADR-0009 (2026-07-12) assumed a topology where the control server ran only on the Owner's own local machine, reachable directly by the Owner's browser — under that assumption, the only safe design was "Ego OS reads status, the Owner clicks buttons on a separate local dashboard for anything state-changing." That assumption stopped being true once the Windows Runner Agent architecture shipped (`automation/WINDOWS_AGENT_VERIFICATION.md`): `automation/control_server.js` now runs co-located with Ego OS itself, as its own systemd unit (`ego-os-runner.service`), and the Owner's browser can only ever reach it *through* Ego OS's own `/automation` page — there is no longer a separate local dashboard for the Owner to click buttons on directly. Enforcing ADR-0009's original prohibition literally would mean the Owner has **no way at all** to pause, resume, or reorder the queue from their own machine — not a safer design, just a non-functional one.

In practice, the code already crossed this line before this ADR: `ego_os/automation_bridge.py`'s `post_runner_command`/`post_task_action`/`post_reorder`, wired into live `POST /automation/runner/{command}`, `POST /automation/tasks/{id}/{action}`, and `POST /automation/tasks/reorder` routes in `ego_os/main.py`, already issue real POST requests to the control server — directly contradicting ADR-0009's own words. This ADR does not pretend that never happened; it evaluates whether the underlying design is actually safe under the Owner's stated conditions, and, since it is (once the gaps below are closed), it formally authorizes it going forward instead of leaving an Accepted ADR silently contradicted by shipped code.

The Owner's approval is conditional, not blanket — see Decision below.

## Decision

Local, Owner-authenticated control of the autonomous runner **from Ego OS itself** is authorized, under every one of these conditions simultaneously:

1. **Loopback only.** The control server this integration talks to must be reachable only via `127.0.0.1`, `::1`, or a hostname that resolves exclusively to a loopback address — checked *after* URL parsing, on the resolved host, never by string-prefix matching on the configured URL.
2. **Approved port only.** The connection must target the control server's own documented port (`4756`) or another value from an explicit, code-defined allowlist — never an arbitrary port supplied at runtime with no validation.
3. **No arbitrary external configuration.** `EGO_OS_CONTROL_SERVER_URL` (or any equivalent override) may only ever *narrow* the target within the loopback/approved-port constraint above — it must never be capable of pointing this integration at a host outside the Owner's own machine. A value that fails validation must cause the integration to fail closed (return "control server unavailable"), never fall back to trusting the invalid value.
4. **No userinfo in the URL.** A control-server URL containing embedded credentials (`http://user:pass@host/`) is rejected outright.
5. **No redirects followed.** Every HTTP call this integration makes must be issued with redirect-following explicitly disabled (not merely relying on a library default that could change) — a redirect response is treated as a failure, never silently followed to a new destination.
6. **State-changing commands go through the existing allowlists, unchanged.** `_RUNNER_COMMANDS`/`_TASK_ACTIONS`/`is_safe_task_id` (`ego_os/automation_bridge.py`) remain the only accepted commands/actions/id shapes; this ADR authorizes the transport, not a widening of what commands exist.
7. **Owner Auth and CSRF are non-negotiable**, exactly as already enforced globally on every Ego OS route (`ego_os/auth.py`) — this ADR creates no exception.
8. **Credentials are never sent to the control server.** No Owner password, API key, or Ego OS session credential is ever included in a request this integration makes — the control server is authenticated only by the fact that it is unreachable from anywhere but this same machine's loopback interface.
9. **Every command produces an audit trail.** A state-changing call through this path is recorded (already true today via the control server's own `events.ndjson`; this ADR requires that record to remain intact and requires a command failure to be surfaced to the Owner, not silently lost behind a redirect that never happens per point 5).
10. **Production fails closed.** If Ego OS ever runs somewhere this integration cannot prove points 1-4 hold (e.g. a misconfigured or missing control server), every route under this ADR must degrade to an honest "unavailable" response — never a 500, never a silent no-op that looks like success.

This authorization covers exactly the three POST paths that exist today (`runner command`, `task action`, `task reorder`) and any equivalent future one that meets all ten conditions — it does not authorize a general-purpose proxy, an arbitrary command channel, or any path reachable from outside Ego OS's own Owner-authenticated surface.

## Consequences

- `ego_os/automation_bridge.py` requires real hardening to actually satisfy conditions 1-5 — today `CONTROL_SERVER_URL` is read from an environment variable with zero validation (`architecture/018` C-02). This ADR is what makes that hardening a requirement, not optional cleanup.
- `architecture/015_RUNNER_OPERATIONS_INTEGRATION.md` is amended with a pointer to this ADR at its forbidden-POST clause — the STRIDE analysis and every other row of that document remain authoritative and unchanged.
- ADR-0009 itself is not edited (Accepted ADRs are never rewritten after the fact) — this document is the record of what changed and why, per this repository's own ADR convention.
- Any future change that would allow a POST reachable from *outside* Ego OS's own Owner-authenticated `/automation*` routes (e.g. a public API, a webhook, a second unauthenticated proxy) is explicitly outside this ADR's authorization and requires its own new ADR and threat model.
