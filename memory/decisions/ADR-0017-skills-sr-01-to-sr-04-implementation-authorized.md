# ADR-0017: SR-01 through SR-04 are Owner-approved and implemented; Skills status documentation is corrected to match

## Status

Accepted by Owner on 2026-07-13, as part of the 2026-07-13 architecture-correction pass. Resolves `architecture/018_ARCHITECTURE_CONTRADICTION_AUDIT_2026-07.md`'s C-11.

Does not reverse or weaken ADR-0004 (Employees compose versioned Skills) or ADR-0005 (Community Skills are untrusted supply-chain input) — this ADR only corrects stale *status headers* on documents whose underlying design those two ADRs already accepted; it changes no community-intake restriction.

## Context

Three independent discovery passes confirmed the same finding: `tasks/queue/SR-01.yaml` through `SR-04.yaml` all carry `"status": "done"`, each with a real commit hash, a real test count (75 tests at SR-01, rising to 103 by SR-04), and recorded production deploy/health-check evidence in their own `result` blocks. `IMPLEMENTATION_ROADMAP.md:136` independently states, in plain prose, that all four are "delivered." `ego_os/skills.py` is real, shipped, tested code (`tests/test_skills_registry.py`, `tests/test_employee_skills.py`, `tests/test_structured_reporting_skill.py`, `tests/test_skills_ui.py`).

Despite this, `architecture/008_SKILLS_AND_CAPABILITY_MANAGEMENT.md:3-5` still reads: "Proposed design. This document defines the target architecture; it does not authorize implementation, Employee migration, dependency installation, external execution, or production changes." `architecture/010_CAPABILITY_DOMAIN_MODEL.md:3-5`, `architecture/011_SKILL_MANIFEST_SPECIFICATION.md:3-5`, and `architecture/012_EMPLOYEE_SKILL_COMPOSITION_CONTRACT.md:3-5` similarly still say "Accepted ... for implementation planning ... does not authorize Registry implementation or Employee migration." These status headers were never revised after SR-01–SR-04 actually shipped — an Accepted-ADR-adjacent design doc left saying "not authorized" about something that has been in production for some time.

## Decision

1. **SR-01, SR-02, SR-03, and SR-04 are recognized as Owner-approved and implemented**, matching their already-recorded `"status": "done"` task results and `IMPLEMENTATION_ROADMAP.md`'s "delivered" language. This is a documentation correction, not a new grant of authority — the work already happened and was already deployed; this ADR closes the gap between that fact and the architecture docs' stale self-description.
2. `architecture/008_SKILLS_AND_CAPABILITY_MANAGEMENT.md`, `architecture/010_CAPABILITY_DOMAIN_MODEL.md`, `architecture/011_SKILL_MANIFEST_SPECIFICATION.md`, and `architecture/012_EMPLOYEE_SKILL_COMPOSITION_CONTRACT.md` have their Status sections updated to state that the Registry foundation, Employee Skill references, the first internal Skill, and the Skills UI/audit trail are implemented (per SR-01–04), while anything in those documents describing *further*, not-yet-built capability (e.g. a package-manager-style external installer, automatic Employee migration tooling beyond what SR-01–04 actually built) remains explicitly "Proposed"/"not yet authorized" — this ADR does not blanket-approve the entirety of every idea in those four documents, only the specific, already-shipped SR-01–04 scope.
3. **No change to community Skill intake restrictions.** ADR-0005's pipeline (Discovery → review → sandbox → tests → approval → Registry, `approved`-only execution, fail-closed revocation) remains fully intact. Community/external Skills are still never automatically executed.
4. **Skills never expand Employee permissions**, restated as still true and unchanged: a Skill's `requirements` are requirements only (`ego_os/skills.py`'s own docstring); what a specialist may actually do is drawn exclusively from the Employee's own `permissions` field (`company/employees/core/*.yaml`), never from a resolved Skill. `SR-02.yaml`'s own acceptance criteria already required and tested this; this ADR reaffirms it as a standing invariant, not something newly granted.
5. **`CHANGELOG.md`'s "[Unreleased]" heading convention is separately addressed** (see this pass's source-of-truth alignment, `architecture/018` C-17) — this ADR does not itself resolve that tension, only the architecture-doc status-header staleness.
6. **v0.5 reprioritization**: Skills work already delivered (SR-01–04) is removed from `IMPLEMENTATION_ROADMAP.md`'s forward-looking v0.5 scope where it is currently listed as pending, and instead recorded under completed work — see this pass's Phase 6 alignment for the exact edit.

## Consequences

- Reading `architecture/008`/`010`/`011`/`012` after this ADR no longer gives a false impression that the Skills Registry is unauthorized or unbuilt — a real, contradiction-causing risk this pass exists to close (a future contributor trusting the stale "Proposed" header could otherwise have proposed re-doing already-shipped, tested work, or worse, concluded the shipped code itself was unauthorized and should be reverted).
- No code change results from this ADR by itself — `ego_os/skills.py` and its tests are unchanged; only the four architecture documents' Status sections and `IMPLEMENTATION_ROADMAP.md`'s v0.5 section are edited.
- Future Skills work genuinely beyond SR-01–04's shipped scope (e.g. a real external-installer pipeline) still requires its own fresh Owner authorization, exactly as before.
