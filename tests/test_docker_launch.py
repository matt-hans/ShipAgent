from pathlib import Path


def test_docker_server_uses_the_validated_listener_launcher():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    command = next(line for line in dockerfile.splitlines() if line.startswith("CMD "))

    assert "python -m src.bundle_entry serve" in command
    assert "uvicorn src.api.main:app" not in command
