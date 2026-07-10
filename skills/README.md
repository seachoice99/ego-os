# Skills Registry

Filesystem-based local Skill Registry (SR-01 of the Skills and Capability
Management initiative — see `architecture/008_SKILLS_AND_CAPABILITY_MANAGEMENT.md`,
`architecture/010_CAPABILITY_DOMAIN_MODEL.md`, `architecture/011_SKILL_MANIFEST_SPECIFICATION.md`,
`architecture/012_EMPLOYEE_SKILL_COMPOSITION_CONTRACT.md`, `memory/decisions/ADR-0004-employees-compose-versioned-skills.md`,
`memory/decisions/ADR-0005-community-skills-are-untrusted-input.md`).

No new database, no new runtime dependency. `ego_os/skills.py` reads and
validates manifests from this directory — it never executes Skill
content, never installs anything, and never grants a permission.

## Layout

```
skills/
  registry/
    <skill_id>/
      <version>/
        manifest.yaml   required manifest (see architecture/011 for the full field spec)
        SKILL.md         (or other entrypoint asset the manifest's entrypoint.path names)
        tests/           optional golden-task/evaluation fixtures for that Skill
```

`<skill_id>` is a stable, lower_snake_case identifier, never reused for a
different capability. `<version>` is exact Semantic Versioning
(`MAJOR.MINOR.PATCH`) and, once published, immutable — a change to the
Skill's behavior is a new version directory, never an edit in place.

## Trust and lifecycle

Only a manifest with `trust.state: approved` and `lifecycle.state: active`
can be resolved for production use via a compatible-version lookup.
`lifecycle.state: revoked` (or `trust.state: revoked`) always fails
closed, even for a caller holding an exact version lock — revocation
overrides an existing lock, per `architecture/011`.

## What this Registry does not do (yet)

Per the initiative's phased scope: no download from GitHub, no community
Skill execution, no MCP installation, no automatic dependency
installation, no cryptographic package signatures, no Capability
Manager, no automatic production-permission changes. Skill requirements
are never permissions — effective authority is always the intersection
of Employee permissions, Skill requirements, Tool policy, and Gate
Control (`architecture/010`).
