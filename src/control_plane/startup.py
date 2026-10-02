from urllib.parse import urlparse

from src.api.middleware.auth import get_expected_api_key, validate_api_key_strength
from src.control_plane.config import AuthMode, ControlPlaneSettings, Environment
from src.utils.network import is_loopback_host

# Host a supported launcher (daemon, bundled sidecar) validated and will bind.
# In-process only: never derived from environment variables a caller could set.
_attested_listener_host: str | None = None


def validate_startup_security(settings: ControlPlaneSettings) -> None:
    if settings.auth_mode == AuthMode.fake_local:
        public_host = (
            urlparse(str(settings.public_base_url)).hostname
            if settings.public_base_url
            else None
        )
        if (
            settings.environment != Environment.local
            or not is_loopback_host(settings.bind_host)
            or (public_host is not None and not is_loopback_host(public_host))
        ):
            raise RuntimeError("fake_local auth is restricted to loopback local mode")


def validate_desktop_listener_security(bind_host: str) -> None:
    """Require a strong SHIPAGENT_API_KEY when the desktop API binds non-loopback.

    Desktop/API-key auth only; hosted Auth0 control-plane startup does not call this.
    """
    if not is_loopback_host(bind_host):
        validate_api_key_strength()
        if not get_expected_api_key():
            raise RuntimeError(
                "Non-loopback listeners require SHIPAGENT_API_KEY authentication"
            )


def validated_listener_host(host: str) -> str:
    """Validate and return the exact host a server launcher will bind."""
    settings = ControlPlaneSettings(bind_host=host)
    validate_startup_security(settings)
    validate_desktop_listener_security(settings.bind_host)
    global _attested_listener_host
    _attested_listener_host = settings.bind_host
    return settings.bind_host


def reset_attested_listener_host() -> None:
    """Forget the launcher-attested host (used by tests)."""
    global _attested_listener_host
    _attested_listener_host = None


def validate_effective_listener_security() -> None:
    """Gate the API lifespan on every host this process is known to bind.

    The lifespan cannot observe uvicorn's bind host. It checks the configured
    ``SHIPAGENT_BIND_HOST`` plus the host a supported launcher attested in
    process. A direct ``uvicorn ... --host`` launch attests nothing; that path
    is enforced per request by the listener guard middleware instead.
    """
    validate_desktop_listener_security(ControlPlaneSettings().bind_host)
    if _attested_listener_host is not None:
        validate_desktop_listener_security(_attested_listener_host)
