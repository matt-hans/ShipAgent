from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.control_plane.auth.context import AuthorizationContext
from src.control_plane.auth.provider_clients import ProviderClientRegistry
from src.control_plane.models import CloudAccount, ProviderConnection


class AuthorizationService:
    def __init__(
        self, db: AsyncSession, clients: ProviderClientRegistry
    ) -> None:
        self.db = db
        self.clients = clients

    async def resolve(
        self, *, subject: str, client_id: str, scopes: set[str]
    ) -> AuthorizationContext:
        surface = self.clients.surface_for(client_id)
        account = await self.db.scalar(
            select(CloudAccount).where(CloudAccount.auth0_subject == subject)
        )
        if account is None:
            account = CloudAccount(auth0_subject=subject)
            self.db.add(account)
            await self.db.flush()

        if account.suspended:
            raise PermissionError("ShipAgent Cloud Account is suspended")

        connection = await self.db.scalar(
            select(ProviderConnection).where(
                ProviderConnection.account_id == account.id,
                ProviderConnection.client_id == client_id,
                ProviderConnection.surface == surface,
            )
        )
        if connection is None:
            connection = ProviderConnection(
                account_id=account.id,
                client_id=client_id,
                surface=surface,
                status="active",
            )
            self.db.add(connection)

        if connection.status != "active":
            raise PermissionError("Provider Connection is not active")

        connection.scopes_text = " ".join(sorted(scopes))
        await self.db.commit()
        return AuthorizationContext(
            account_id=account.id,
            provider_connection_id=connection.id,
            provider_surface=surface,
            subject=subject,
            client_id=client_id,
            scopes=frozenset(scopes),
        )
