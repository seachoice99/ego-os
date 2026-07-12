# Skills and Capability Management

## Status and scope

**Implemented for SR-01 through SR-04** (Owner-approved per `ADR-0017`, 2026-07-13): the Skill Registry foundation, Employee Skill references, the first internal Skill, and the Skills UI/audit trail described here are real, shipped, tested code (`ego_os/skills.py`, `tests/test_skills_registry.py` and siblings) — this is no longer a "does not authorize implementation" placeholder for that scope. Anything in this document describing further capability beyond SR-01–04's actual shipped scope (e.g. a package-manager-style external installer, automated Employee migration tooling) remains a **Proposed design** requiring its own fresh Owner authorization before implementation, exactly as before.

## Relationship to existing architecture

Employees remain versioned competence containers under ADR-0002. This design normalizes reusable procedures already implied by the `skills` field in `architecture/001_CORE_ENTITIES.md`. Model Providers and Tools remain replaceable Infrastructure. Gate Control in `architecture/006_AUTONOMOUS_COMPANY_ARCHITECTURE.md` remains the highest execution authority.

## Definitions and boundaries

- **Employee:** owns role, mission, responsibilities, composition references, reporting, and cost policy.
- **Persona:** describes who the Employee is and what it is accountable for.
- **Knowledge:** authorized internal information made available for a task; it is not embedded into a Skill package.
- **Skill:** a reusable, versioned procedure with declared inputs, outputs, requirements, tests, and provenance.
- **Tool:** replaceable Infrastructure that can perform an external action; credentials remain at Infrastructure level.
- **Policy:** permissions, approval thresholds, environment constraints, cost limits, and Gate Control rules.

Selection does not imply authorization. Effective execution authority is the intersection of Employee permissions, Skill requirements, Tool policy, task approval, environment policy, and current Gate Control tier.

## Minimum Skill manifest

A schema selected in Phase 1 must include:

- stable ID, name, description, semantic version, and schema version;
- origin type, source revision or content digest, author, and license;
- trust and lifecycle state;
- compatible Ego OS runtime and provider-adapter ranges;
- entrypoint or instruction assets with integrity digests;
- Skill dependencies;
- required Knowledge classes, Tools, permissions, and network/filesystem constraints;
- test suite and evaluation criteria;
- approval record and rollback target.

The exact serialization, signature model, and lockfile format require Owner and architecture approval.

## Local Skill Registry

The Registry owns Skill packages, manifests, immutable versions, provenance, trust state, compatibility data, test evidence, lifecycle state, and append-only audit events. It must provide deterministic lookup and version resolution, Employee attachment and detachment, compatibility checks, update, disable, revoke, and rollback operations. Mutable upstream references are not executable identities.

Provider adapters translate an approved Employee composition into runtime-specific inputs. Registry and manifest semantics must not depend exclusively on Claude Code, Codex, or one model provider.

## Community capability intake

External content is quarantined and treated as data, not authority. Intake follows ADR-0005. Inspection and tests run in a deny-by-default sandbox without secrets, production Knowledge, or production Tool credentials. Audit events cover import, review, approval, attachment, execution-relevant changes, revocation, and rollback.

## Capability Manager

Capability Manager is a future system service, Employee, or hybrid that:

- identifies capability gaps from authorized task outcomes and Employee requirements;
- discovers community Skills, MCP servers, libraries, and other reusable capabilities;
- compares fitness, freshness, maintenance, license, security, and cost;
- submits candidates to quarantine and sandbox evaluation;
- produces a Capability Report and integration recommendation;
- updates Registry metadata only within explicit policy;
- never promotes an external capability to production without required approval.

The MVP ends at recommendation and manual approval. Controlled autonomy is deferred until registry lifecycle controls, permissions, evaluations, sandboxing, audit, rollback, rate limits, and kill switches have operational evidence.

## Organizational memory

Idea → RFC/design document when needed → ADR → roadmap item → task queue → implementation → validation → capability available to Employees.

Conversation is not authoritative until the decision is recorded in Git. Completion of an implementation task must update related architecture, roadmap, task, and operational documentation.

## Owner decisions still required

- acceptance of ADR-0004 and ADR-0005;
- canonical manifest serialization, signatures, version constraints, and lockfile;
- approval roles and thresholds for each trust and permission level;
- sandbox technology and required isolation guarantees;
- audit retention and privacy policy;
- whether Capability Manager is an Employee, service, or hybrid;
- whether any narrowly scoped automated production promotion is ever allowed.

## Risks

Supply-chain compromise, license violations, prompt or behavior regression, privilege escalation, provider lock-in, nondeterministic dependency resolution, audit leakage, stale or revoked capabilities, and premature autonomous self-modification.
