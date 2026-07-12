# Capability Domain Model

## Status

Accepted by Owner on 2026-07-10 under ADR-0004. **Registry implementation for SR-01 through SR-04 is now Owner-approved and shipped** (`ADR-0017`, 2026-07-13) — the "does not authorize Registry implementation" restriction no longer applies to that already-implemented scope. Employee migration/registry work genuinely beyond SR-01–04 still requires its own fresh authorization.

## Purpose

Define ownership boundaries between Employee, Persona, Knowledge, Skill, Tool, and Policy so composition never implies authority and reusable behavior is not duplicated across Employee prompts.

## Entities

### Employee

A versioned Definition representing an accountable competence container.

Owns:

- stable Employee ID and Employee definition version;
- Persona reference or inline Persona during migration;
- Skill requirements;
- required model capabilities;
- Tool references;
- reporting and cost policy references;
- organization placement.

Does not own credentials, runtime sessions, project data, Skill implementations, or provider-specific model IDs.

### Persona

A versioned Definition of role and accountability.

Owns title, department, mission, responsibilities, escalation expectations, and communication stance. Persona answers who the Employee is and what outcome it owns. It must not contain reusable procedures, secrets, Tool implementations, or model-provider configuration.

### Knowledge

A versioned or task-scoped reference to authorized information.

Owns source identity, classification, scope, freshness, retrieval rules, and access policy. Knowledge answers what information may be made available. A Skill may declare required Knowledge classes but cannot package production Knowledge or grant itself access.

### Skill

A reusable, versioned procedure with declared inputs, outputs, requirements, evaluation evidence, and provenance.

Owns process instructions, contracts, dependencies, failure behavior, tests, and compatibility. Skill answers how a repeatable capability is performed. It does not own Persona, production Knowledge, credentials, or final execution authority.

### Tool

Replaceable Infrastructure that performs an external or privileged action.

Owns runtime implementation, argument contract, required permission, context injection contract, output/artifact type, operational limits, and credential resolution. The current `ego_os/tools.py` registry is the implementation baseline. A Skill references Tool IDs and required permissions; it never imports a Tool implementation directly.

### Policy

A versioned rule set that constrains selection and execution.

Owns permissions, approval thresholds, Gate Control mapping, environment/network/filesystem constraints, budget, data handling, audit, and rollback requirements. Policy can deny an otherwise valid composition. A lower layer cannot override a higher policy.

## Authority calculation

Selection and authorization are distinct:

1. Task planning identifies required outcome capabilities.
2. Employee matching selects an accountable Employee.
3. Composition resolves Persona, Skills, Knowledge requirements, Tools, and Policies.
4. Compatibility validation checks versions and runtime/provider support.
5. Authorization computes the intersection of Employee permissions, Skill requirements, Tool permission, Knowledge access policy, task approval, environment policy, budget, and current Gate Control tier.
6. Runtime receives only the authorized subset. Any missing required permission fails closed before execution.

No Skill, Tool, Employee, or provider adapter can widen the authority supplied by Policy and Gate Control.

## Identity and history

- Every Definition has a stable ID and immutable version.
- A Task execution record locks exact Employee, Persona, Skill, Policy, and adapter versions or content digests.
- Updating a Definition creates a new version; it never rewrites historical attribution.
- Knowledge snapshots record source version/digest and retrieval time when reproducibility is required.
- Tool implementations record a version or deploy revision in operational logs.

## Migration from current Employee YAML

The existing YAML shape remains valid during migration. Its fields map as follows:

| Current field | Target owner |
|---|---|
| `id`, `version`, `department` | Employee |
| `name`, `title`, `mission`, `responsibilities` | Persona |
| `required_capabilities` | Employee outcome/model requirements; procedural items migrate to Skills after audit |
| `reporting_rules` | Policy, with Employee reference |
| `permissions` | Policy grants referenced by Employee |

No field is removed until Phase 3 provides golden-task regression evidence and a rollback path.

## Schema-level acceptance criteria

- Each field has one authoritative owner.
- Skills can be reused without copying Persona, Knowledge, Tool implementation, or permissions.
- The same Employee composition can be rendered by more than one provider adapter.
- A complete composition can be locked and reproduced from stored versions/digests.
- Missing or revoked dependencies and permissions fail before model or Tool execution.
