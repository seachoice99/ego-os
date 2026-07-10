# Skill Manifest Specification

## Status

Accepted by Owner on 2026-07-10 for implementation planning under ADR-0004 and ADR-0005. No registry or loader is implemented by this document.

## Canonical representation

The initial human-authored format is YAML encoded as UTF-8. Registry identity and integrity use a deterministic canonical serialization defined by the future Registry implementation; hashing raw YAML bytes is insufficient because semantically equivalent YAML may differ in formatting.

## Required manifest shape

```yaml
schema_version: "1.0"
id: presentation_review
version: "1.0.0"
name: Presentation Review
description: Evaluate a presentation against its goal, audience, evidence, narrative, and visual clarity.
origin:
  type: internal
  source: ego-os
  revision: null
  digest: sha256:...
  author: FiveSeven
  license: proprietary
trust:
  state: approved
  approved_by: owner
  approved_at: 2026-07-10T00:00:00Z
compatibility:
  ego_os: ">=0.5,<1.0"
  manifest_schema: "1.x"
entrypoint:
  type: instructions
  path: SKILL.md
  digest: sha256:...
dependencies:
  skills: []
requirements:
  model_capabilities: [vision, structured_output]
  knowledge_classes: [project_context]
  tools: []
  permissions: [read_project_context]
  network: none
  filesystem: none
contracts:
  input_schema: schemas/input.json
  output_schema: schemas/output.json
tests:
  suite: tests/evaluations.yaml
  minimum_score: 0.85
lifecycle:
  state: active
  replaces: null
  rollback_to: null
```

## Field rules

- `schema_version`: manifest contract version, independent of Skill version.
- `id`: stable lower snake-case ID; never reused for a different capability.
- `version`: Semantic Versioning. Breaking input/output, authority requirement, or meaning changes increment major.
- `origin`: immutable provenance. Community imports require source URL, immutable upstream revision, retrieval time, original license, and original digest in the intake record.
- `trust.state`: one of `discovered`, `quarantined`, `reviewing`, `approved`, `deprecated`, `revoked`. Only `approved` can be resolved for production.
- `entrypoint`: artifact type, relative path, and digest. Paths cannot escape the package root.
- `dependencies.skills`: stable ID plus explicit compatible version range; floating branches and unbounded latest references are forbidden.
- `requirements`: requirements only, never grants. Policy decides whether they are satisfied.
- `contracts`: machine-validatable input and output schemas. Secret values cannot appear in defaults or examples.
- `tests`: deterministic functional cases plus evaluation criteria for nondeterministic output.
- `lifecycle`: operational availability. `revoked` fails closed even when a lock references the version.

## Version resolution and lock record

Resolution is deterministic:

1. Filter to trusted and lifecycle-eligible versions.
2. Filter by Ego OS, manifest schema, runtime, adapter, and dependency compatibility.
3. Select the highest compatible stable version unless an Employee lock pins an exact version.
4. Resolve the full dependency graph; cycles and conflicts are errors.
5. Produce a lock record containing exact versions and content digests.
6. Validate lock integrity before each execution boundary.

Automatic major-version upgrades are forbidden. Revocation overrides an existing lock. A rollback selects an already approved exact version and creates an auditable lock update.

## Trust and lifecycle transitions

Allowed trust transitions:

```text
discovered → quarantined → reviewing → approved
approved → deprecated → revoked
reviewing → quarantined
approved → revoked
```

Reapproval is a new reviewed version or explicit new approval event; mutation of an approved package is forbidden. Lifecycle and trust events record actor, authority, timestamp, reason, previous state, new state, and artifact digest.

## Dependency safety

- Transitive dependencies inherit no permissions from their parent.
- The effective requirement set is the union of declared requirements, but execution authority remains the policy intersection.
- Dependency depth, total package size, and graph size require configurable limits.
- An unavailable, incompatible, tampered, or revoked dependency blocks composition.
- External code dependencies remain governed by the normal dependency and supply-chain process; declaring them in a Skill does not install them.

## Owner decisions

Accepted on 2026-07-10:

- YAML is the initial human-authored manifest format and must be schema-validated.
- Skills use Semantic Versioning.
- Production execution locks an exact approved Skill version and digest. A newer compatible version may be recommended and tested automatically, but does not replace the production lock without the configured approval.
- The MVP uses Git history plus SHA-256 content digests for internal Skills. Cryptographic package signatures are required before community Skills or autonomous updates can be promoted to production.
- Skills with no external action may be approved after required tests by an authorized policy role.
- Network access or local file writes require enhanced review and explicit permission grants.
- Production access, secrets, payments, publication, and irreversible actions always require Owner approval.

Still to be specified during Registry design: signature key custody, default compatibility ranges, deprecation periods, and the exact authorized roles below Owner level. These details cannot weaken the accepted approval tiers above.
