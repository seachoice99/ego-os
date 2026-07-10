# Employee–Skill Composition Contract

## Status

Accepted by Owner on 2026-07-10 for implementation planning. It defines a provider-neutral intermediate representation, not a runtime implementation.

## Design rule

Domain Definitions produce one provider-neutral `ExecutionComposition`. Provider adapters consume that composition and render provider-specific messages, tool declarations, and structured-output settings. Provider adapters cannot modify authority, resolve new dependencies, or silently add Knowledge and Tools.

## Composition input

```yaml
task:
  id: task-123
  project_id: project-7
  requested_capabilities: [presentation_review]
employee:
  id: designer
  version: "1.2"
persona:
  id: designer
  version: "1.2"
skills:
  - id: presentation_review
    version: "1.0.0"
    digest: sha256:...
knowledge:
  - id: project_context
    version_or_digest: sha256:...
tools: []
policies:
  - id: default_execution
    version: "1.0.0"
runtime:
  adapter_id: provider_adapter
  adapter_version: "1.0.0"
```

Every reference is exact by execution time. Version ranges may exist in Employee definitions but must be resolved into a lock before composition.

## ExecutionComposition output

The composition layer emits:

- task objective and typed input contract;
- Persona instructions;
- ordered Skill instruction assets;
- authorized Knowledge excerpts with source metadata;
- authorized Tool schemas from the existing Tool registry;
- output contract;
- applicable reporting, cost, privacy, and Gate Control constraints;
- exact definition/package/adapter versions and digests;
- audit correlation ID;
- denied optional requirements and hard-failure reasons.

It never emits credentials, raw policy secrets, unapproved package contents, hidden chain-of-thought requests, or Tools outside the authorized set.

## Deterministic assembly order

1. Validate Task and Employee identity.
2. Resolve and lock Employee, Persona, Skills, and Policies.
3. Validate dependency graph, trust, lifecycle, compatibility, and integrity.
4. Resolve Knowledge references under task and project scope.
5. Resolve Tool declarations from the Infrastructure registry.
6. Calculate effective authority and budget.
7. Fail closed if any required item is denied or missing.
8. Emit the immutable ExecutionComposition.
9. Pass it to a selected compatible provider adapter.
10. Record versions, decisions, and operational events in Task/Report/Memory without raw hidden reasoning.

Skill ordering is explicit. A Skill cannot overwrite higher-priority Policy, Persona accountability, or Task objective. Conflicting Skill contracts are a composition error rather than last-write-wins behavior.

## Provider adapter boundary

An adapter may:

- map Persona and Skill instruction sections to provider message roles;
- map authorized Tool schemas to provider function/tool formats;
- select supported structured-output and multimodal features;
- normalize provider responses into the declared output contract;
- report usage, latency, model revision, and errors.

An adapter may not:

- add or remove permissions;
- load undeclared Skills, Knowledge, or Tools;
- change trust/lifecycle decisions;
- choose an incompatible model silently;
- suppress audit, cost, or approval requirements;
- persist provider-specific identifiers into core domain Definitions.

## Capability matching

Employee `required_capabilities` currently mixes outcome capabilities and implementation capabilities. Migration classifies each entry as:

- outcome capability used for staffing;
- model capability used for provider selection;
- procedural capability supplied by a Skill;
- Tool capability supplied by Infrastructure.

Matching first finds an accountable Employee by outcome capability, then validates that a composition can satisfy procedural, model, Knowledge, Tool, and Policy requirements. A Tool existing in `TOOLS` does not prove the Employee is authorized to use it.

## Compatibility proof

The contract is acceptable only when the same locked composition can be rendered by at least two adapter fixtures with equivalent authorized Tools, input/output contract, and policy constraints. Provider-specific syntax may differ; domain meaning and authority must not.

## Failure behavior

- Missing/revoked/tampered Skill: fail before provider invocation.
- Dependency conflict or cycle: fail composition with an actionable report.
- Missing required permission or Knowledge access: fail closed.
- Optional Tool denied: omit only when the Skill contract declares a valid no-Tool fallback.
- Adapter lacks a required capability: select another compatible adapter or return a capability gap.
- Runtime failure after invocation: retain the exact lock and audit correlation ID for retry/diagnosis.
