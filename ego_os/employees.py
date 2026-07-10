from pathlib import Path

import yaml

from ego_os import store

REGISTRY_DIR = Path(__file__).parent.parent / "company" / "employees" / "core"


def sync_from_registry():
    """Load every Employee Definition from the YAML registry and upsert it
    into the store. Existing status (idle/assigned) is left untouched for
    employees that already exist. Also diffs the Skill references
    against what was already on record and logs an "attached"/"detached"
    Skill audit event (SR-04) for each real change -- not on every
    startup sync, only when a reference actually appears or disappears."""
    import json

    for path in sorted(REGISTRY_DIR.glob("*.yaml")):
        with open(path, "r", encoding="utf-8") as f:
            definition = yaml.safe_load(f)

        existing = store.get_employee(definition["id"])
        previous_skills = json.loads(existing["skills"]) if existing is not None else []
        new_skills = definition.get("skills", [])

        store.upsert_employee(
            id=definition["id"],
            name=definition["name"],
            title=definition["title"],
            department=definition["department"],
            mission=definition["mission"],
            required_capabilities=definition.get("required_capabilities", []),
            permissions=definition.get("permissions", []),
            version=str(definition["version"]),
            # Optional (SR-02): a list of {"id", "version"} Skill references.
            # Absent for every pre-existing Employee YAML -- defaults to []
            # and behaves exactly as before ADR-0004's Skill composition.
            skills=new_skills,
        )

        previous_refs = {(s["id"], s["version"]) for s in previous_skills}
        new_refs = {(s["id"], s["version"]) for s in new_skills}
        for skill_id, version in new_refs - previous_refs:
            store.log_skill_audit_event(
                skill_id, "attached", skill_version=version,
                detail=f"Attached to employee '{definition['id']}' (v{definition['version']})",
            )
        for skill_id, version in previous_refs - new_refs:
            store.log_skill_audit_event(
                skill_id, "detached", skill_version=version,
                detail=f"Detached from employee '{definition['id']}'",
            )
