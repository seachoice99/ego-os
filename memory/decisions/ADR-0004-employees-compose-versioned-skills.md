# ADR-0004: Employees compose versioned Skills

## Status

Accepted by Owner on 2026-07-10.

## Context

ADR-0002 defines Employees as versioned competence containers. Current Employee definitions place mission, responsibilities, required capabilities, tools, and permissions in one definition, while `architecture/001_CORE_ENTITIES.md` already lists `skills` as an Employee field. Reusable procedures are not yet defined as independent entities, so the same competence would have to be repeated across multiple Employees.

## Decision

An Employee remains the versioned competence container and is composed from distinct layers:

- Persona: role, mission, and responsibilities;
- Knowledge: authorized company and project information;
- Skills: reusable procedures the Employee can apply;
- Tools: replaceable external capabilities;
- Policies: permissions, Gate Control, cost, and reporting constraints.

A Skill is an independent, versioned Definition referenced by stable ID and compatible version constraint. One Skill may be used by multiple Employees. Skills do not grant Knowledge, Tool access, credentials, or authority: effective authority remains the intersection of Employee permissions, Skill requirements, runtime policy, and Gate Control.

Skill composition and provider adapters must remain independent of any single model or agent host. Existing Employee definitions may only be migrated through a separate inventory, regression-test, and rollout task.

## Consequences

- Reusable competence can be maintained and tested once.
- Employee version history remains authoritative for work already performed.
- Skill manifests, dependency resolution, compatibility, and provenance become required architecture.
- Existing Employee YAML files are unchanged until an approved migration plan exists.
