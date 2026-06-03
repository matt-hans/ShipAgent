import json
from pathlib import Path
from typing import Any

from src.registry.models import RegistrySchema


def registry_to_json_dict(registry: RegistrySchema) -> dict[str, Any]:
    return registry.model_dump(mode="json")


def write_registry_snapshot(path: Path, registry: RegistrySchema) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = registry_to_json_dict(registry)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
