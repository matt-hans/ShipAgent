import pytest

from src.control_plane.config import ControlPlaneSettings, Environment
from src.control_plane.startup import validate_startup_security


def mk_settings(**overrides):
    data = {
        "auth_mode": "fake_local",
        "bind_host": "127.0.0.1",
        "public_base_url": "http://127.0.0.1:8080",
        "environment": Environment.local,
        "database_url": "postgresql+asyncpg://shipagent:shipagent@localhost/shipagent",
        "redis_url": "redis://localhost:6379/0",
    }
    data.update(overrides)
    return ControlPlaneSettings(**data)


def test_validate_startup_security_raises_for_public_bind_host():
    with pytest.raises(RuntimeError, match="loopback"):
        validate_startup_security(mk_settings(bind_host="0.0.0.0"))


def test_validate_startup_security_skips_when_runtime_urls_missing():
    validate_startup_security(
        mk_settings(database_url=None, redis_url=None),
    )
