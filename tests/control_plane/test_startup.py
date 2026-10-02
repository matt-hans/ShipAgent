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


@pytest.mark.parametrize(
    "overrides",
    [
        {"bind_host": "0.0.0.0"},
        {"public_base_url": "https://relay.example.com"},
        {"environment": Environment.production},
    ],
)
def test_validate_startup_security_rejects_insecure_fake_local_without_runtime_urls(
    overrides,
):
    with pytest.raises(RuntimeError, match="loopback"):
        validate_startup_security(
            mk_settings(database_url=None, redis_url=None, **overrides)
        )


def test_validate_startup_security_skips_when_runtime_urls_missing():
    validate_startup_security(
        mk_settings(database_url=None, redis_url=None),
    )


def test_auth0_hosted_public_bind_does_not_require_desktop_api_key(monkeypatch):
    """Hosted Auth0 identity (ADR 0001) must not depend on the desktop API key."""
    monkeypatch.delenv("SHIPAGENT_API_KEY", raising=False)
    validate_startup_security(
        ControlPlaneSettings(
            auth_mode="auth0",
            bind_host="0.0.0.0",
            environment=Environment.production,
            public_base_url="https://relay.example.com",
        )
    )


def test_desktop_listener_still_requires_api_key_on_public_bind(monkeypatch):
    """The desktop/API-key gate stays on the launcher listener path."""
    from src.control_plane.startup import validated_listener_host

    monkeypatch.delenv("SHIPAGENT_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SHIPAGENT_API_KEY"):
        validated_listener_host("0.0.0.0")
    monkeypatch.setenv("SHIPAGENT_API_KEY", "s" * 64)
    assert validated_listener_host("0.0.0.0") == "0.0.0.0"


def test_launcher_validation_leaves_no_process_global_state(monkeypatch):
    """A launcher's validation must not poison later app lifespans (issue #48).

    The launcher validates and binds before the app starts; the app lifespan
    gates only its own configuration, so a stale launcher host can never make an
    unrelated lifespan (another test, a restarted app) fail.
    """
    from src.control_plane import startup

    monkeypatch.setenv("SHIPAGENT_API_KEY", "s" * 64)
    startup.validated_listener_host("0.0.0.0")
    monkeypatch.delenv("SHIPAGENT_API_KEY", raising=False)
    monkeypatch.delenv("SHIPAGENT_BIND_HOST", raising=False)
    startup.validate_effective_listener_security()  # must not raise


def test_lifespan_gate_rejects_configured_public_bind_without_key(monkeypatch):
    from src.control_plane import startup

    monkeypatch.delenv("SHIPAGENT_API_KEY", raising=False)
    monkeypatch.setenv("SHIPAGENT_BIND_HOST", "0.0.0.0")
    with pytest.raises(RuntimeError, match="SHIPAGENT_API_KEY"):
        startup.validate_effective_listener_security()
