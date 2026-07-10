"""Skill Registry foundation (SR-01). Registry only reads/validates
manifests -- it never executes Skill content and never grants a
permission. Every test builds its own manifests under tmp_path; nothing
here touches the real skills/registry/ directory.
"""

import hashlib

import pytest

from ego_os import skills


def _digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _write_skill(root, skill_id, version, *, trust_state="approved", lifecycle_state="active",
                  entrypoint_content=b"# A real skill entrypoint.\n", entrypoint_digest=None,
                  entrypoint_path="SKILL.md", manifest_id=None, manifest_version=None,
                  extra_fields=None, raw_yaml=None):
    """Write a real, on-disk skill package under tmp_path and return its
    directory. By default everything is internally consistent and valid;
    individual tests override one field at a time to build a specific
    failure case."""
    package_dir = root / skill_id / version
    package_dir.mkdir(parents=True, exist_ok=True)
    entrypoint_file = package_dir / entrypoint_path
    entrypoint_file.write_bytes(entrypoint_content)
    digest = entrypoint_digest if entrypoint_digest is not None else _digest(entrypoint_content)

    if raw_yaml is not None:
        (package_dir / "manifest.yaml").write_text(raw_yaml, encoding="utf-8")
        return package_dir

    manifest = {
        "schema_version": "1.0",
        "id": manifest_id if manifest_id is not None else skill_id,
        "version": manifest_version if manifest_version is not None else version,
        "name": "Test Skill",
        "description": "A skill used only for registry tests.",
        "origin": {"type": "internal", "source": "ego-os", "revision": None, "digest": "sha256:" + "0" * 64, "author": "test", "license": "proprietary"},
        "trust": {"state": trust_state, "approved_by": "owner", "approved_at": "2026-07-10T00:00:00Z"},
        "compatibility": {"ego_os": ">=0.4,<1.0", "manifest_schema": "1.x"},
        "entrypoint": {"type": "instructions", "path": entrypoint_path, "digest": digest},
        "dependencies": {"skills": []},
        "requirements": {"model_capabilities": [], "knowledge_classes": [], "tools": [], "permissions": [], "network": "none", "filesystem": "none"},
        "lifecycle": {"state": lifecycle_state, "replaces": None, "rollback_to": None},
    }
    if extra_fields:
        manifest.update(extra_fields)

    import yaml
    (package_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    return package_dir


# --- valid manifest -----------------------------------------------------

def test_valid_manifest_loads(tmp_path):
    package_dir = _write_skill(tmp_path, "structured_reporting", "1.0.0")
    manifest = skills.load_manifest(package_dir)
    assert manifest["id"] == "structured_reporting"
    assert manifest["version"] == "1.0.0"
    assert manifest["_version_tuple"] == (1, 0, 0)


# --- malformed YAML ------------------------------------------------------

def test_malformed_yaml_is_rejected(tmp_path):
    package_dir = tmp_path / "broken_yaml" / "1.0.0"
    package_dir.mkdir(parents=True)
    (package_dir / "manifest.yaml").write_text("id: [this is not\n  valid: yaml: at all", encoding="utf-8")
    with pytest.raises(skills.SkillValidationError, match="not valid YAML"):
        skills.load_manifest(package_dir)


# --- missing required field ----------------------------------------------

def test_missing_required_field_is_rejected(tmp_path):
    package_dir = _write_skill(tmp_path, "incomplete_skill", "1.0.0")
    import yaml
    manifest = yaml.safe_load((package_dir / "manifest.yaml").read_text(encoding="utf-8"))
    del manifest["description"]
    (package_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    with pytest.raises(skills.SkillValidationError, match="missing required field"):
        skills.load_manifest(package_dir)


# --- invalid ID -----------------------------------------------------------

@pytest.mark.parametrize("bad_id", ["Bad-ID", "1starts_with_digit", "has spaces", "UPPERCASE", ""])
def test_invalid_id_is_rejected(tmp_path, bad_id):
    package_dir = _write_skill(tmp_path, "placeholder_dir", "1.0.0", manifest_id=bad_id)
    with pytest.raises(skills.SkillValidationError, match="invalid skill id"):
        skills.load_manifest(package_dir)


# --- invalid version -------------------------------------------------------

@pytest.mark.parametrize("bad_version", ["1.0", "1.0.0-beta", "v1.0.0", "1.0.0.0", "latest"])
def test_invalid_version_is_rejected(tmp_path, bad_version):
    package_dir = _write_skill(tmp_path, "placeholder_dir", "1.0.0", manifest_version=bad_version)
    with pytest.raises(skills.SkillValidationError, match="invalid version"):
        skills.load_manifest(package_dir)


# --- bad digest -------------------------------------------------------------

def test_digest_mismatch_is_rejected(tmp_path):
    package_dir = _write_skill(tmp_path, "tampered_skill", "1.0.0", entrypoint_digest="sha256:" + "a" * 64)
    with pytest.raises(skills.SkillValidationError, match="digest mismatch"):
        skills.load_manifest(package_dir)


def test_malformed_digest_field_is_rejected(tmp_path):
    package_dir = _write_skill(tmp_path, "bad_digest_format", "1.0.0", entrypoint_digest="not-a-real-digest")
    with pytest.raises(skills.SkillValidationError, match="entrypoint.digest must be"):
        skills.load_manifest(package_dir)


# --- path traversal ----------------------------------------------------------

def test_path_traversal_is_rejected(tmp_path):
    package_dir = _write_skill(tmp_path, "traversal_attempt", "1.0.0")
    import yaml
    manifest = yaml.safe_load((package_dir / "manifest.yaml").read_text(encoding="utf-8"))
    manifest["entrypoint"]["path"] = "../../../etc/passwd"
    (package_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    with pytest.raises(skills.SkillValidationError, match="escapes the package root"):
        skills.load_manifest(package_dir)


def test_absolute_entrypoint_path_is_rejected(tmp_path):
    package_dir = _write_skill(tmp_path, "absolute_path_attempt", "1.0.0")
    import os
    import yaml
    manifest = yaml.safe_load((package_dir / "manifest.yaml").read_text(encoding="utf-8"))
    manifest["entrypoint"]["path"] = "C:\\Windows\\win.ini" if os.name == "nt" else "/etc/passwd"
    (package_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    with pytest.raises(skills.SkillValidationError, match="must be relative"):
        skills.load_manifest(package_dir)


# --- missing entrypoint --------------------------------------------------

def test_missing_entrypoint_file_is_rejected(tmp_path):
    package_dir = _write_skill(tmp_path, "no_entrypoint", "1.0.0")
    (package_dir / "SKILL.md").unlink()
    with pytest.raises(skills.SkillValidationError, match="entrypoint file not found"):
        skills.load_manifest(package_dir)


# --- duplicate id+version --------------------------------------------------

def test_duplicate_id_version_is_rejected_on_listing(tmp_path):
    _write_skill(tmp_path, "shared_name", "1.0.0")
    # A second directory whose manifest *claims* the same identity as the first.
    _write_skill(tmp_path, "shared_name_copy", "1.0.0", manifest_id="shared_name", manifest_version="1.0.0")
    with pytest.raises(skills.SkillValidationError, match="duplicate skill id\\+version"):
        skills.list_skills(tmp_path)


def test_manifest_identity_must_match_its_own_directory(tmp_path):
    """A manifest stored at <id>/<version>/ but internally claiming a
    different id/version is an integrity problem, caught directly by
    load_manifest when it knows where the package is stored."""
    package_dir = _write_skill(tmp_path, "outer_name", "1.0.0", manifest_id="different_name")
    with pytest.raises(skills.SkillValidationError, match="stored under"):
        skills.load_manifest(package_dir, expected_id="outer_name", expected_version="1.0.0")


# --- revoked skill fails closed --------------------------------------------

def test_revoked_skill_fails_closed_on_exact_lookup(tmp_path):
    _write_skill(tmp_path, "revoked_skill", "1.0.0", trust_state="revoked", lifecycle_state="revoked")
    with pytest.raises(skills.SkillRevokedError):
        skills.get_exact_version("revoked_skill", "1.0.0", tmp_path)


def test_revoked_skill_excluded_from_compatible_resolution(tmp_path):
    _write_skill(tmp_path, "revoked_skill", "1.0.0", trust_state="revoked", lifecycle_state="revoked")
    with pytest.raises(skills.SkillNotFoundError):
        skills.resolve_compatible_version("revoked_skill", None, tmp_path)


def test_load_manifest_still_reports_error_message_no_stack_trace(tmp_path):
    """The error text itself must be a clean, direct message -- suitable
    for a UI to show as-is, not a Python traceback."""
    _write_skill(tmp_path, "revoked_skill", "1.0.0", trust_state="revoked", lifecycle_state="revoked")
    try:
        skills.get_exact_version("revoked_skill", "1.0.0", tmp_path)
        assert False, "expected SkillRevokedError"
    except skills.SkillRevokedError as exc:
        message = str(exc)
        assert "Traceback" not in message
        assert "revoked_skill@1.0.0" in message


# --- deterministic listing --------------------------------------------------

def test_listing_is_deterministic_and_sorted(tmp_path):
    _write_skill(tmp_path, "zeta_skill", "1.0.0")
    _write_skill(tmp_path, "alpha_skill", "2.0.0")
    _write_skill(tmp_path, "alpha_skill", "1.0.0")

    first = skills.list_skills(tmp_path)
    second = skills.list_skills(tmp_path)
    ids_and_versions = [(m["id"], m["version"]) for m in first]
    assert ids_and_versions == [("alpha_skill", "1.0.0"), ("alpha_skill", "2.0.0"), ("zeta_skill", "1.0.0")]
    assert ids_and_versions == [(m["id"], m["version"]) for m in second]


def test_listing_surfaces_one_bad_manifest_without_breaking_the_rest(tmp_path):
    _write_skill(tmp_path, "good_skill", "1.0.0")
    _write_skill(tmp_path, "bad_skill", "1.0.0", raw_yaml="not: [valid yaml: at all")

    results = skills.list_skills(tmp_path)
    good = [r for r in results if r.get("id") == "good_skill"]
    bad = [r for r in results if r.get("id") == "bad_skill"]
    assert len(good) == 1
    assert len(bad) == 1
    assert "error" in bad[0]


# --- exact version resolution -----------------------------------------------

def test_exact_version_resolution(tmp_path):
    _write_skill(tmp_path, "multi_version_skill", "1.0.0")
    _write_skill(tmp_path, "multi_version_skill", "1.1.0")
    manifest = skills.get_exact_version("multi_version_skill", "1.0.0", tmp_path)
    assert manifest["version"] == "1.0.0"


def test_exact_version_not_found(tmp_path):
    _write_skill(tmp_path, "multi_version_skill", "1.0.0")
    with pytest.raises(skills.SkillNotFoundError):
        skills.get_exact_version("multi_version_skill", "9.9.9", tmp_path)


# --- compatible version resolution -----------------------------------------

def test_compatible_version_resolution_picks_highest_eligible(tmp_path):
    _write_skill(tmp_path, "multi_version_skill", "1.0.0")
    _write_skill(tmp_path, "multi_version_skill", "1.1.0")
    _write_skill(tmp_path, "multi_version_skill", "2.0.0")
    manifest = skills.resolve_compatible_version("multi_version_skill", ">=1.0.0,<2.0.0", tmp_path)
    assert manifest["version"] == "1.1.0"


def test_compatible_version_resolution_ignores_non_approved_versions(tmp_path):
    _write_skill(tmp_path, "multi_version_skill", "1.0.0")
    _write_skill(tmp_path, "multi_version_skill", "1.1.0", trust_state="reviewing")
    manifest = skills.resolve_compatible_version("multi_version_skill", None, tmp_path)
    assert manifest["version"] == "1.0.0"


# --- incompatible version ----------------------------------------------------

def test_incompatible_version_range_raises_not_found(tmp_path):
    _write_skill(tmp_path, "multi_version_skill", "1.0.0")
    with pytest.raises(skills.SkillNotFoundError, match="compatible"):
        skills.resolve_compatible_version("multi_version_skill", ">=2.0.0", tmp_path)


def test_version_satisfies_helper():
    assert skills.version_satisfies((1, 5, 0), ">=1.0.0,<2.0.0") is True
    assert skills.version_satisfies((2, 0, 0), ">=1.0.0,<2.0.0") is False
    assert skills.version_satisfies((1, 0, 0), "==1.0.0") is True
    assert skills.version_satisfies((1, 0, 1), "==1.0.0") is False
    assert skills.version_satisfies((1, 0, 0), None) is True


# --- unknown skill id ---------------------------------------------------------

def test_unknown_skill_id_raises_not_found(tmp_path):
    with pytest.raises(skills.SkillNotFoundError):
        skills.get_exact_version("does_not_exist", "1.0.0", tmp_path)
    with pytest.raises(skills.SkillNotFoundError):
        skills.resolve_compatible_version("does_not_exist", None, tmp_path)
