# ADR-0005: Community Skills are untrusted supply-chain input

## Status

Accepted by Owner on 2026-07-10.

## Context

Community Skills, MCP servers, libraries, and similar reusable capabilities may contain malicious instructions, unsafe code, vulnerable dependencies, incompatible licenses, or mutable upstream behavior. Executing them directly from GitHub would bypass Ego OS permissions and Gate Control.

## Decision

External capability candidates never execute directly from an external repository. They pass through:

Discovery → source and license review → security review → sandbox → functional tests → adaptation to Ego OS → human or authorized-agent approval → Approved Skill Registry.

Every candidate retains source, immutable revision or digest, license, review evidence, tests, trust state, approver, and the internally adapted artifact. Trust states are `discovered`, `quarantined`, `reviewing`, `approved`, `deprecated`, and `revoked`. Only approved versions may be attached to production Employees. Revoked versions fail closed.

Automated discovery and sandbox testing may be permitted by policy. Production promotion always requires the configured approval level, and no Skill may widen its own permissions.

## Consequences

- Intake is slower but reproducible, auditable, and reversible.
- Provenance, licensing, sandboxing, revocation, and rollback are first-class requirements.
- Installing or running external Skills, MCP servers, or dependencies requires a separate authorized task.
