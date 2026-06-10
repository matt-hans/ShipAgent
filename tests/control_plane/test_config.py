import pytest

from src.control_plane.config import AuthMode, ControlPlaneSettings, Environment


def settings(**updates):
    values = {
        "auth_mode": AuthMode.fake_local,
        "bind_host": "127.0.0.1",
        "public_base_url": "http://127.0.0.1:8080",
        "environment": Environment.local,
        "database_url": "postgresql+asyncpg://shipagent:shipagent@localhost/shipagent",
        "redis_url": "redis://localhost:6379/0",
    }
    values.update(updates)
    return ControlPlaneSettings(**values)


def test_fake_auth_accepts_loopback_only():
    from src.control_plane.startup import validate_startup_security

    validate_startup_security(settings())


@pytest.mark.parametrize(
    "updates",
    [
        {"bind_host": "0.0.0.0"},
        {"public_base_url": "https://dev-mcp.shipagent.app"},
        {"environment": "prototype"},
    ],
)
def test_fake_auth_rejects_public_or_deployed_modes(updates):
    from src.control_plane.startup import validate_startup_security

    with pytest.raises(RuntimeError, match="fake_local"):
        validate_startup_security(settings(**updates))

