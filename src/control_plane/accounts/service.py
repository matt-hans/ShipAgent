"""Fail-closed account deletion with explicit legal-hold and Redis cleanup."""

from dataclasses import dataclass

from sqlalchemy import delete

from src.control_plane.audit.authorization_ledger import AuthorizationLedgerService
from src.control_plane.audit.hash_validation import require_sha256_hex
from src.control_plane.audit.models import ControlPlaneLegalHold
from src.control_plane.audit.service import ControlPlaneAuditService
from src.control_plane.models import CloudAccount, ProviderConnection
from src.control_plane.retention.legal_hold import LegalHoldService, lock_account


@dataclass(frozen=True)
class AccountDeletionResult:
    account_deleted: bool
    provider_connections_deleted: int
    audit_events_deleted: int
    authorization_ledger_events_deleted: int


class CloudAccountDeletionService:
    @classmethod
    async def delete_account(
        cls, *, session, account_id: str, actor_id_hash: str, state_store
    ) -> AccountDeletionResult:
        """Caller commits SQL; Redis failure prevents deleting durable account state.

        If a later SQL commit fails, ephemeral metadata may already be removed:
        this is safely unavailable, never reconstructed from the ledger.
        """
        require_sha256_hex(actor_id_hash)
        account = await lock_account(session, account_id, required=False)
        if await LegalHoldService.has_active_hold(
            session=session, account_id=account_id
        ):
            raise PermissionError("active legal hold")
        # Do not delete SQL evidence/account first and leave usable ephemeral state.
        await state_store.cleanup_for_account(account_id)
        ledger = await AuthorizationLedgerService.cleanup_for_account(
            session=session, account_id=account_id
        )
        audit = await ControlPlaneAuditService.cleanup_for_account(
            session=session, account_id=account_id
        )
        await session.execute(
            delete(ControlPlaneLegalHold).where(
                ControlPlaneLegalHold.account_id == account_id
            )
        )
        connections = await session.execute(
            delete(ProviderConnection).where(
                ProviderConnection.account_id == account_id
            )
        )
        await session.execute(delete(CloudAccount).where(CloudAccount.id == account_id))
        return AccountDeletionResult(
            account is not None, connections.rowcount or 0, audit, ledger
        )
