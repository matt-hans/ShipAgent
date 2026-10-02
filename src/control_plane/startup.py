from urllib.parse import urlparse

from src.api.middleware.auth import get_expected_api_key, validate_api_key_strength
from src.control_plane.config import AuthMode, ControlPlaneSettings, Environment
from src.utils.network import is_loopback_host


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
    """Validate and return the exact host a server launcher will bind.

    Launchers (daemon, bundled sidecar) call this before binding, so an unsafe
    host fails before any socket opens. Stateless by design: nothing is retained
    for the app lifespan, which gates only its own configuration.
    """
    settings = ControlPlaneSettings(bind_host=host)
    validate_startup_security(settings)
    validate_desktop_listener_security(settings.bind_host)
    return settings.bind_host


def validate_effective_listener_security() -> None:
    """Gate the API lifespan on the configured ``SHIPAGENT_BIND_HOST``.

    The lifespan cannot observe uvicorn's bind host. A direct
    ``uvicorn ... --host`` launch is enforced per request by the listener guard
    middleware against the real socket addresses instead.
    """
    validate_desktop_listener_security(ControlPlaneSettings().bind_host)
