"""Dormant reservation actions over the shared private source-fence owner."""

from src.services.source_ingress.reservation_contracts import (
    MAX_SOURCE_LIFETIME,
    MAX_UPLOAD_LIFETIME,
    ReservationError,
    ReservationReceipt,
    ReservationRequest,
    SourceOperatorContext,
)
from src.services.source_ingress.source_fences import (
    AuthorityFence as AuthorityFence,
)
from src.services.source_ingress.source_fences import (
    HeldSourceOperation,
    SourceFenceExecutor,
)
from src.services.source_ingress.source_fences import (
    SourceAuthority as SourceAuthority,
)


class SourceReservationCoordinator(SourceFenceExecutor):
    def reserve(
        self,
        *,
        operator_context: SourceOperatorContext,
        provider_connection_id: str,
        conversation_reference: str,
        request: ReservationRequest,
    ) -> ReservationReceipt:
        if type(request) is not ReservationRequest:
            raise ReservationError("invalid_request")
        return self._run_action(
            operator_context=operator_context,
            provider_connection_id=provider_connection_id,
            conversation_reference=conversation_reference,
            request_key=request.request_key,
            action=lambda held: self._reservation_action(held, request),
        )

    def recover(
        self,
        *,
        operator_context: SourceOperatorContext,
        provider_connection_id: str,
        conversation_reference: str,
        request_key: str,
    ) -> ReservationReceipt:
        return self._run_action(
            operator_context=operator_context,
            provider_connection_id=provider_connection_id,
            conversation_reference=conversation_reference,
            request_key=request_key,
            action=lambda held: self._reservation_action(held, None),
        )

    @staticmethod
    def _reservation_action(
        held: HeldSourceOperation, request: ReservationRequest | None
    ) -> ReservationReceipt:
        existing = held.source.lookup(held.namespace)
        now = held.require_current()
        if existing is not None:
            receipt = existing.to_receipt()
            held.set_result(receipt)
            held.set_response_expiry(receipt.upload_expires_at)
            held.require_response_time()
            if request is not None and existing.request != request:
                raise ReservationError("request_conflict")
        elif request is None:
            raise ReservationError("reservation_unavailable")
        else:
            admitted_at = int(now)
            record = held.source.insert(
                held.namespace,
                request,
                admitted_revision=held.owned.revision,
                admitted_at=admitted_at,
                upload_expires_at=min(
                    admitted_at + MAX_UPLOAD_LIFETIME, held.owned.expires_at
                ),
                prospective_source_expires_at=min(
                    admitted_at + MAX_SOURCE_LIFETIME, held.owned.expires_at
                ),
            )
            receipt = record.to_receipt()
            held.set_result(receipt)
            held.set_response_expiry(receipt.upload_expires_at)
            held.require_current()
            held.require_response_time()
            held.commit()
        return receipt
