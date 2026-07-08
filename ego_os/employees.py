from pathlib import Path

import yaml

from ego_os import store

REGISTRY_DIR = Path(__file__).parent.parent / "company" / "employees" / "core"


def sync_from_registry():
    """Load every Employee Definition from the YAML registry and upsert it
    into the store. Existing status (idle/assigned) is left untouched for
    employees that already exist."""
    for path in sorted(REGISTRY_DIR.glob("*.yaml")):
        with open(path, "r", encoding="utf-8") as f:
            definition = yaml.safe_load(f)
        store.upsert_employee(
            id=definition["id"],
            name=definition["name"],
            title=definition["title"],
            department=definition["department"],
            mission=definition["mission"],
            version=str(definition["version"]),
        )
