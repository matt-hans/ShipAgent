#!/usr/bin/env python
from pathlib import Path

from src.registry.catalog import load_registry
from src.registry.export import write_registry_snapshot

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "generated" / "provider_artifacts"


def main() -> None:
    registry = load_registry()
    write_registry_snapshot(OUT / "registry.json", registry)


if __name__ == "__main__":
    main()
