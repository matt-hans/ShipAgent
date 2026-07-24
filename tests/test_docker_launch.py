import sys
from pathlib import Path
from unittest.mock import patch

import yaml
from dotenv import dotenv_values

from src.api.middleware.auth import validate_api_key_strength


def documented_docker_environment() -> dict[str, str]:
    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
    configured_files = compose["services"]["shipagent"]["env_file"]
    environment: dict[str, str] = {}
    for configured_file in configured_files:
        path = (
            Path(".env.example") if configured_file == ".env" else Path(configured_file)
        )
        environment.update(
            {
                key: value
                for key, value in dotenv_values(path).items()
                if value is not None
            }
        )
    return environment


def test_docker_server_uses_the_validated_listener_launcher():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    command = next(line for line in dockerfile.splitlines() if line.startswith("CMD "))

    assert "python -m src.bundle_entry serve" in command
    assert "uvicorn src.api.main:app" not in command


def test_documented_docker_environment_starts_authenticated_public_launcher(
    monkeypatch,
):
    import src.bundle_entry as bundle_entry

    docker_environment = documented_docker_environment()
    docker_environment["SHIPAGENT_API_KEY"] = "d" * 64
    for key, value in docker_environment.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(
        sys,
        "argv",
        ["shipagent-core", "serve", "--host", "0.0.0.0", "--port", "8080"],
    )

    validate_api_key_strength()
    with patch("uvicorn.Server.run") as server_run:
        bundle_entry.main()

    server_run.assert_called_once()
