"""Skill Registry (SR-01, Skills and Capability Management initiative).

Filesystem-based, no new database, no new runtime dependency -- Semantic
Version and compatibility-range support here is a small, hand-rolled
subset (MAJOR.MINOR.PATCH and a comma-separated list of
>=/<=/==/>/< constraints), not a third-party semver library, since that
subset is all the accepted manifest spec (architecture/011) actually
needs for this MVP.

Per architecture/008, architecture/010, architecture/011,
architecture/012, ADR-0004, and ADR-0005: this module only reads and
validates Skill manifests. It never executes, imports, or evaluates
Skill content, never installs anything, and never grants a permission --
a Skill's `requirements` are requirements only; Policy (and, in this
codebase, an Employee's own `permissions`) decides what is actually
authorized. Every manifest is untrusted input to validate, not a
trusted program to run.
"""

import hashlib
import re
from pathlib import Path

import yaml

REGISTRY_ROOT = Path(__file__).parent.parent / "skills" / "registry"

_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_CONSTRAINT_RE = re.compile(r"^(>=|<=|==|>|<)\s*(\d+\.\d+\.\d+)$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

_TRUST_STATES = {"discovered", "quarantined", "reviewing", "approved", "deprecated", "revoked"}
_LIFECYCLE_STATES = {"active", "deprecated", "revoked"}

_REQUIRED_FIELDS = (
    "schema_version", "id", "version", "name", "description",
    "origin", "trust", "compatibility", "entrypoint", "requirements", "lifecycle",
)


class SkillError(Exception):
    """Base class for every Skill Registry failure. Always a clean,
    human-readable message -- caught at the UI boundary and shown
    directly, never as a raw stack trace."""


class SkillValidationError(SkillError):
    """A manifest (or the package it belongs to) fails validation:
    malformed YAML, a missing/invalid field, a path-traversal attempt,
    a missing entrypoint file, a digest mismatch, or an identity
    (id/version) inconsistent with where it's stored."""


class SkillNotFoundError(SkillError):
    """No manifest matches the requested id/version/range."""


class SkillRevokedError(SkillError):
    """The only or best-matching version is revoked. Always fails
    closed, even for an exact-version lookup that would otherwise
    resolve fine -- revocation overrides an existing lock."""


def _parse_version(version_str):
    match = _VERSION_RE.match(version_str) if isinstance(version_str, str) else None
    if not match:
        raise SkillValidationError(f"invalid version {version_str!r}: must be MAJOR.MINOR.PATCH")
    return tuple(int(part) for part in match.groups())


def _parse_constraint(constraint_str):
    match = _CONSTRAINT_RE.match(constraint_str.strip())
    if not match:
        raise SkillValidationError(f"invalid version constraint {constraint_str!r}")
    op, version_str = match.groups()
    return op, _parse_version(version_str)


_OPS = {
    ">=": lambda v, b: v >= b,
    "<=": lambda v, b: v <= b,
    "==": lambda v, b: v == b,
    ">": lambda v, b: v > b,
    "<": lambda v, b: v < b,
}


def version_satisfies(version_tuple, range_str):
    """range_str is a comma-separated list of constraints, e.g.
    '>=1.0.0,<2.0.0'. An empty/None range is satisfied by anything."""
    if not range_str:
        return True
    for part in range_str.split(","):
        op, bound = _parse_constraint(part)
        if not _OPS[op](version_tuple, bound):
            return False
    return True


def _compute_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_safe_path(package_dir: Path, relative_path) -> Path:
    """Never allow an entrypoint to escape its own package directory --
    no absolute paths, no '..' traversal, resolved and checked against
    the real package root."""
    if not isinstance(relative_path, str) or not relative_path:
        raise SkillValidationError(f"entrypoint.path must be a non-empty relative path, got {relative_path!r}")
    if Path(relative_path).is_absolute():
        raise SkillValidationError(f"entrypoint.path must be relative, got absolute path {relative_path!r}")
    package_dir_resolved = package_dir.resolve()
    candidate = (package_dir_resolved / relative_path).resolve()
    if not candidate.is_relative_to(package_dir_resolved):
        raise SkillValidationError(f"entrypoint.path escapes the package root: {relative_path!r}")
    return candidate


def load_manifest(package_dir: Path, expected_id: str = None, expected_version: str = None) -> dict:
    """Parse and fully validate one manifest.yaml. Raises SkillValidationError
    (never a bare exception) for any problem. Does not execute or read
    the entrypoint's content beyond hashing it for the digest check."""
    package_dir = Path(package_dir)
    manifest_path = package_dir / "manifest.yaml"
    if not manifest_path.is_file():
        raise SkillValidationError(f"no manifest.yaml in {package_dir}")

    try:
        raw = manifest_path.read_text(encoding="utf-8")
        manifest = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise SkillValidationError(f"manifest.yaml at {package_dir} is not valid YAML: {exc}")

    if not isinstance(manifest, dict):
        raise SkillValidationError(f"manifest.yaml at {package_dir} must be a mapping, got {type(manifest).__name__}")

    missing = [field for field in _REQUIRED_FIELDS if field not in manifest]
    if missing:
        raise SkillValidationError(f"manifest at {package_dir} missing required field(s): {', '.join(missing)}")

    skill_id = manifest["id"]
    if not isinstance(skill_id, str) or not _ID_RE.match(skill_id):
        raise SkillValidationError(f"invalid skill id {skill_id!r}: must be lower_snake_case, starting with a letter")

    version_str = manifest["version"]
    version_tuple = _parse_version(version_str)  # raises SkillValidationError if malformed

    if expected_id is not None and skill_id != expected_id:
        raise SkillValidationError(
            f"manifest at {package_dir} declares id {skill_id!r} but is stored under {expected_id!r}"
        )
    if expected_version is not None and version_str != expected_version:
        raise SkillValidationError(
            f"manifest at {package_dir} declares version {version_str!r} but is stored under {expected_version!r}"
        )

    trust = manifest.get("trust")
    trust_state = trust.get("state") if isinstance(trust, dict) else None
    if trust_state not in _TRUST_STATES:
        raise SkillValidationError(f"invalid trust.state {trust_state!r} in {package_dir}")

    lifecycle = manifest.get("lifecycle")
    lifecycle_state = lifecycle.get("state") if isinstance(lifecycle, dict) else None
    if lifecycle_state not in _LIFECYCLE_STATES:
        raise SkillValidationError(f"invalid lifecycle.state {lifecycle_state!r} in {package_dir}")

    entrypoint = manifest.get("entrypoint")
    if not isinstance(entrypoint, dict):
        raise SkillValidationError(f"entrypoint must be a mapping in {package_dir}")
    declared_digest = entrypoint.get("digest")
    if not isinstance(declared_digest, str) or not _DIGEST_RE.match(declared_digest):
        raise SkillValidationError(
            f"entrypoint.digest must be 'sha256:<64 hex chars>' in {package_dir}, got {declared_digest!r}"
        )
    entrypoint_file = _resolve_safe_path(package_dir, entrypoint.get("path"))
    if not entrypoint_file.is_file():
        raise SkillValidationError(f"entrypoint file not found: {entrypoint.get('path')!r} (in {package_dir})")
    actual_digest = _compute_digest(entrypoint_file)
    if actual_digest != declared_digest:
        raise SkillValidationError(
            f"entrypoint digest mismatch for {skill_id}@{version_str}: "
            f"manifest declares {declared_digest}, actual content hashes to {actual_digest}"
        )

    manifest["_version_tuple"] = version_tuple
    manifest["_package_dir"] = package_dir
    return manifest


def _iter_package_dirs(registry_root: Path):
    if not registry_root.is_dir():
        return
    for skill_dir in sorted(p for p in registry_root.iterdir() if p.is_dir()):
        for version_dir in sorted(p for p in skill_dir.iterdir() if p.is_dir()):
            if (version_dir / "manifest.yaml").is_file():
                yield skill_dir.name, version_dir.name, version_dir


def list_skills(registry_root: Path = None) -> list:
    """Deterministic listing of every manifest under the registry root,
    sorted by (id, version). A manifest that fails validation is
    surfaced as an {"id", "version", "error"} entry rather than raised
    (one bad package must not break the whole listing) -- except a
    genuine duplicate id+version, which is a registry integrity error
    and is raised, since it means two packages claim the same logical
    identity somewhere in the tree (this check is intentionally *not*
    the same as the directory-vs-manifest identity check in
    _load_all_versions: a duplicate can occur between two directories
    whose own names don't have to match either manifest)."""
    root = Path(registry_root) if registry_root is not None else REGISTRY_ROOT
    seen = {}
    results = []
    for dir_id, dir_version, package_dir in _iter_package_dirs(root):
        try:
            manifest = load_manifest(package_dir)
        except SkillError as exc:
            results.append({"id": dir_id, "version": dir_version, "error": str(exc)})
            continue
        key = (manifest["id"], manifest["version"])
        if key in seen:
            raise SkillValidationError(
                f"duplicate skill id+version {key[0]}@{key[1]}: found at both {seen[key]} and {package_dir}"
            )
        seen[key] = package_dir
        results.append(manifest)
    results.sort(key=lambda m: (m.get("id", ""), m.get("_version_tuple", (0, 0, 0))))
    return results


def _load_all_versions(skill_id: str, registry_root: Path):
    skill_dir = Path(registry_root) / skill_id
    if not skill_dir.is_dir():
        raise SkillNotFoundError(f"no such skill: {skill_id!r}")
    manifests = []
    for version_dir in sorted(p for p in skill_dir.iterdir() if p.is_dir()):
        if (version_dir / "manifest.yaml").is_file():
            manifests.append(load_manifest(version_dir, expected_id=skill_id, expected_version=version_dir.name))
    if not manifests:
        raise SkillNotFoundError(f"no valid versions found for skill: {skill_id!r}")
    return manifests


def _fail_closed_if_revoked(manifest: dict) -> dict:
    if manifest["trust"]["state"] == "revoked" or manifest["lifecycle"]["state"] == "revoked":
        raise SkillRevokedError(f"{manifest['id']}@{manifest['version']} is revoked")
    return manifest


def get_exact_version(skill_id: str, version: str, registry_root: Path = None) -> dict:
    """Look up one exact, immutable version. Fails closed if that exact
    version is revoked -- revocation always overrides an existing lock,
    even an exact one (architecture/011)."""
    root = Path(registry_root) if registry_root is not None else REGISTRY_ROOT
    manifests = _load_all_versions(skill_id, root)
    matches = [m for m in manifests if m["version"] == version]
    if not matches:
        raise SkillNotFoundError(f"{skill_id}@{version} not found")
    return _fail_closed_if_revoked(matches[0])


def resolve_compatible_version(skill_id: str, version_range: str = None, registry_root: Path = None) -> dict:
    """Resolve the highest trusted (approved + active) version
    satisfying version_range (or simply the highest trusted version if
    version_range is None), per architecture/011's resolution order:
    filter to trusted/lifecycle-eligible first, then by compatibility,
    then take the highest stable match."""
    root = Path(registry_root) if registry_root is not None else REGISTRY_ROOT
    manifests = _load_all_versions(skill_id, root)
    eligible = [m for m in manifests if m["trust"]["state"] == "approved" and m["lifecycle"]["state"] == "active"]
    if version_range:
        eligible = [m for m in eligible if version_satisfies(m["_version_tuple"], version_range)]
    if not eligible:
        raise SkillNotFoundError(
            f"no approved, active version of {skill_id!r} compatible with {version_range!r}"
        )
    return max(eligible, key=lambda m: m["_version_tuple"])
