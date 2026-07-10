# Initiative: Skills and Capability Management

## Metadata

- ID: SCM
- Project: ego-os
- Status: Phase 1 architecture accepted; implementation remains blocked pending completion/prioritization of current v0.5 work
- Priority: P2 overall; Phase 1 becomes P1 only when scheduled
- Created: 2026-07-10
- Owner employee: orchestrator
- Assigned employees: none

## Goal and rationale

Separate reusable Skills from Employee definitions, create a controlled local Registry, and later add a Capability Manager. This removes duplicated competence while preserving ADR-0002, provider neutrality, permissions, Gate Control, provenance, and rollback.

## Queue

| ID | Phase | Priority | Task | Dependencies | Affected components | Acceptance and completion criteria | Risks | Required approval | Documents to update |
|---|---:|---:|---|---|---|---|---|---|---|
| SCM-01 | 1 | P1 | Define Employee, Persona, Knowledge, Skill, Tool, and Policy schemas and boundaries | ADR-0004 accepted | architecture, Employee model | Documentation complete and accepted on 2026-07-10 in `architecture/010_CAPABILITY_DOMAIN_MODEL.md` | overlapping entities | Approved: Owner | architecture/001, 005, 008, 010 |
| SCM-02 | 1 | P1 | Specify Skill manifest, versioning, dependencies, provenance, trust, and lifecycle | SCM-01; ADR-0005 accepted | manifest, policy | Documentation complete and accepted on 2026-07-10 in `architecture/011_SKILL_MANIFEST_SPECIFICATION.md`; remaining operational details belong to Registry design | nondeterminism, license gaps | Approved: Owner; security review still required for implementation | architecture/008, 011 |
| SCM-03 | 1 | P1 | Define provider-neutral composition and adapter contract | SCM-01, SCM-02 | runtime, model providers | Contract accepted on 2026-07-10 in `architecture/012_EMPLOYEE_SKILL_COMPOSITION_CONTRACT.md`; two-adapter fixture proof is an implementation acceptance test | provider lock-in | Approved: Owner | architecture/000, 008, 012 |
| SCM-04 | 2 | P1 | Design Registry storage, metadata, search, audit, compatibility, update, disable, revoke, and rollback | SCM-02, SCM-03 | Registry, store, audit | Threat model and storage design approved; deterministic resolution specified | corruption, audit leakage | Owner + security + architecture | architecture/008; roadmap |
| SCM-05 | 2 | P1 | Implement and test minimal local Skill Registry | SCM-04; separate implementation assignment | ego_os, tests | Unit/integration tests pass; no external execution; rollback demonstrated | migration and integrity bugs | Owner | implementation docs, changelog |
| SCM-06 | 2 | P1 | Implement Employee attachment and compatibility resolution | SCM-05 | employees, lifecycle, registry | Attach/detach/version lock tested without changing historical task attribution | behavior regression | Architecture | employee architecture, tests |
| SCM-07 | 3 | P2 | Inventory current Employee definitions and select 2–3 repeated internal capabilities | SCM-01 | company/employees | Evidence-based candidates and migration boundaries reviewed | false reuse | Employee owners | initiative report |
| SCM-08 | 3 | P2 | Package selected internal Skills and create golden-task evaluations | SCM-05, SCM-07 | registry, employees, tests | Each Skill independently passes evaluations | prompt regression | Employee owners + QA | registry docs, tests |
| SCM-09 | 3 | P2 | Migrate multiple Employees through a staged plan | SCM-06, SCM-08 | Employee YAML, lifecycle | No duplication; golden tasks show no regression; rollback works | production regression | Owner + Employee owners | registry, employee versions, changelog |
| SCM-10 | 4 | P2 | Specify non-executing candidate import, provenance, license, and static analysis | SCM-02, SCM-04 | intake, security | Candidate can be stored without execution and has immutable provenance | supply chain, licensing | Security + Owner/legal | architecture/008, security checklist |
| SCM-11 | 4 | P2 | Define and validate deny-by-default sandbox | SCM-10; separate infrastructure assignment | sandbox, policies | Escape, secret, network, filesystem, and resource-limit tests pass | sandbox escape | Owner + security | deployment/security docs |
| SCM-12 | 4 | P2 | Implement evaluations, approval workflow, adaptation, and promotion | SCM-05, SCM-10, SCM-11 | registry, approvals, audit | Only approved adapted artifacts can become executable; revocation fails closed | approval bypass | Owner + security | architecture, operations, tests |
| SCM-13 | 5 | P3 | Define capability-gap signals and Capability Report | SCM-09, SCM-12 | task lifecycle, reports | Report is actionable and does not expose hidden reasoning or secrets | noisy recommendations | Owner | reporting architecture, template |
| SCM-14 | 5 | P3 | Build Capability Manager MVP: discovery, comparison, recommendation, manual approval | SCM-13; external access separately authorized | service/Employee, registry | Benchmark candidates compared; no automatic production promotion | unsafe recommendation | Owner + security | registry, employee/service docs |
| SCM-15 | 5 | P3 | Monitor stale, vulnerable, deprecated, and revoked Skills | SCM-12, SCM-14 | registry, operations | Alerts and fail-closed revocation tested | stale intelligence | Security | operations docs |
| SCM-16 | 6 | P3 | Define controlled-autonomy policy, evaluations, rate limits, audit, rollback, and kill switches | Operational evidence from SCM-14/15 | policies, Gate Control | Explicit policy and failure tests approved | self-modification | Owner + security | architecture/006, 008 |
| SCM-17 | 6 | P3 | Pilot automated discovery and tests in sandbox only | SCM-16 | Capability Manager, sandbox | Bounded pilot meets quality/security thresholds with no production writes | resource abuse | Owner + security | capability report, operations |
| SCM-18 | 6 | P3 | Evaluate narrowly scoped automated integration | SCM-17 evidence; separate authorization | registry, Gate Control | Reversible, policy-bounded experiment passes predeclared criteria | production compromise | Owner | ADR, roadmap, operations |

## Scheduling

- Documentation and Owner review can happen immediately without touching runtime code.
- Phases 1–2 belong in the nearest milestone only after current critical v0.5 work is explicitly prioritized against them.
- Phase 3 follows a working Registry.
- Phases 4–5 are later releases.
- Phase 6 is premature until governance and operational evidence exist.
- SCM-01, SCM-02, SCM-04, SCM-10, and SCM-11 are prerequisites for safe autonomous capability development.

Phase 1 audit evidence and first extraction candidates are recorded in `tasks/SCM_PHASE1_AUDIT.md`.

## Global completion rule

Each task is complete only when dependency evidence exists, required approval is recorded, tests or document validation pass, risks and rollback are documented, and all listed documents are updated. No task authorizes dependency installation, community Skill execution, production changes, commit, push, merge, or deploy without a separate explicit Owner request.
