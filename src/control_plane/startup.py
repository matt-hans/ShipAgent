import ipaddress
from urllib.parse import urlparse

from src.control_plane.config import AuthMode, ControlPlaneSettings, Environment


def _is_loopback_host(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return value == "localhost"


def validate_startup_security(settings: ControlPlaneSettings) -> None:
    if settings.auth_mode == AuthMode.fake_local and (
        not settings.database_url or not settings.redis_url
    ):
        # Control plane runtime settings are unavailable in dev/test/desktop flows.
        # Keep deterministic startup for non-control-plane environments.
        return

    if settings.auth_mode != AuthMode.fake_local:
        return

    public_host = (
        urlparse(str(settings.public_base_url)).hostname if settings.public_base_url else None
    )
    if (
        settings.environment != Environment.local
        or not _is_loopback_host(settings.bind_host)
        or (public_host is not None and not _is_loopback_host(public_host))
    ):
        raise RuntimeError("fake_local auth is restricted to loopback local mode")
