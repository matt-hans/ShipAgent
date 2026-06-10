from types import MappingProxyType


class ProviderClientRegistry:
    """Map Auth0 OAuth client IDs to provider surfaces."""

    def __init__(self, clients: dict[str, str]) -> None:
        self._clients = MappingProxyType(dict(clients))

    def surface_for(self, client_id: str) -> str:
        """Resolve a trusted provider surface for an Auth0 client ID."""
        surface = self._clients.get(client_id)
        if surface is None:
            raise PermissionError("token was not issued to an authorized provider client")
        return surface
