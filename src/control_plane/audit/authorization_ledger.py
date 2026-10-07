"""Allowlisted evidence only; SQL records are never executable authority."""

from dataclasses import dataclass

from src.control_plane.audit.hash_validation import (
    require_account_id,
    require_connection_id,
    require_reference,
    require_sha256_hex,
)
from src.registry.identifiers import ShipAgentIdFamily
from src.registry.tools.public import RATE_CURRENCY_CODES


@dataclass(frozen=True, repr=False)
class AuthorizationMetadata:
    """Safe hashes and opaque references shared by ephemeral state and SQL audit."""

    account_id: str
    provider_connection_id: str
    approval_request_id: str
    preview_hash: str
    purchase_scope_hash: str
    authorized_amount_minor: int | None = None
    currency: str | None = None
    approving_subject_hash: str | None = None
    execution_target_fingerprint_hash: str | None = None
    idempotency_key_hash: str | None = None
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        require_account_id(self.account_id)
        require_connection_id(self.provider_connection_id)
        require_reference(self.approval_request_id, ShipAgentIdFamily.APPROVAL_REQUEST)
        require_sha256_hex(self.preview_hash)
        require_sha256_hex(self.purchase_scope_hash)
        for value in (self.approving_subject_hash, self.execution_target_fingerprint_hash, self.idempotency_key_hash):
            if value is not None:
                require_sha256_hex(value)
        if self.correlation_id is not None:
            require_reference(self.correlation_id, ShipAgentIdFamily.CORRELATION)
        amount = self.authorized_amount_minor
        if amount is not None and (type(amount) is not int or not 0 <= amount < 2**63):
            raise ValueError("invalid authorized amount")
        if (amount is None) != (self.currency is None):
            raise ValueError("amount and currency must be supplied together")
        if self.currency is not None and self.currency not in RATE_CURRENCY_CODES:
            raise ValueError("unsupported canonical currency")
