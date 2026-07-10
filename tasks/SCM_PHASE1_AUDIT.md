# SCM Phase 1 Audit: Current Employee Capabilities

## Metadata

- Initiative: SCM
- Tasks: SCM-01, SCM-02, SCM-03; input to SCM-07
- Status: documentation complete; Phase 1 architecture accepted by Owner on 2026-07-10
- Date: 2026-07-10
- Scope: `company/employees/core/*.yaml`, `architecture/001`, `architecture/005`, `ego_os/tools.py`, model selection policy

## Findings

The current Employee YAML shape contains Persona, outcome capabilities, procedural capabilities, reporting Policy, and permission grants in one document. This is compatible with ADR-0002 but requires classification before extraction.

The runtime Tool registry is already separate and permission-gated. It should remain Infrastructure and become a dependency target for Skills, not be moved into Skill packages.

## Candidate reusable internal Skills

### Structured review

Evidence:

- QA compares output to request, finds gaps, checks completeness, and requests revision.
- Designer critiques visual materials.
- Orchestrator ensures delivery and reporting quality.

Candidate boundary: typed evaluation rubric, evidence-linked findings, pass/revise outcome, and actionable corrections. Persona-specific accountability and approval authority remain outside the Skill.

### Evidence synthesis

Evidence:

- Researcher compares sources, separates facts from assumptions, highlights uncertainty, and produces actionable summaries.
- Orchestrator and CFO also compare options and produce recommendations.

Candidate boundary: source assessment, claim/evidence mapping, uncertainty labels, and decision-oriented synthesis. Live web access remains a Tool permission, not part of the Skill.

### Structured reporting

Evidence:

- Every Employee has reporting rules.
- Coder reports changed files and tests.
- CFO reports usage and cost drivers.
- Orchestrator logs staffing decisions.
- QA reports concrete issues and status.

Candidate boundary: report assembly against a declared schema with evidence, decisions, outputs, open risks, usage, and cost sections. Role-specific required fields remain Policy configuration.

## Capabilities that should not become shared Skills yet

- `build_presentation_sites`: currently a deterministic Tool plus Designer accountability; extraction would duplicate Infrastructure.
- `create_documents` and `create_finance_reports`: permissions mapped to Tools, not procedures.
- `coding`: too broad; split only after task-history evidence reveals stable repeated procedures.
- `reasoning`, `attention_to_detail`, `tone_control`, `visual_thinking`: model/persona selection qualities, not independently testable Skill packages as currently defined.
- Employee creation and staffing: core orchestration workflow with Gate Control implications; not a first extraction candidate.

## Risks discovered

- `required_capabilities` mixes staffing, model, Skill, and Tool concepts.
- Permissions currently live directly in Employee YAML; migration could accidentally broaden access if Skill requirements are mistaken for grants.
- Reporting rules repeat structurally but differ in mandatory role-specific evidence.
- A generic review Skill could erase domain-specific standards unless its rubric is parameterized and evaluated per domain.
- Existing historical tasks do not lock Skill versions because Skills do not yet exist; migration must preserve Employee-version attribution.

## Recommendation

Use `structured_reporting` as the first low-risk internal Skill candidate after the Registry exists. Use `evidence_synthesis` second. Pilot `structured_review` only with separate QA and presentation-review evaluation fixtures. Do not extract deterministic Tools or broad cognitive traits.

No Employee YAML or runtime code should change before SCM-05/06 exist and SCM-08 provides golden-task evaluations.
