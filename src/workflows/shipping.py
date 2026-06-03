from typing import Protocol
from uuid import uuid4

from src.carriers.models import RateRequest, RateResult
from src.workflows.models import (
    PreviewShipmentsRequest,
    PreviewShipmentsResult,
    PreviewShipmentsSummary,
)


class CarrierGateway(Protocol):
    async def rate(self, request: RateRequest) -> RateResult: ...


class ShippingWorkflowService:
    """Provider-neutral shipping workflow facade."""

    def __init__(self, carrier_gateway: CarrierGateway) -> None:
        self._carrier_gateway = carrier_gateway

    async def preview_shipments(
        self, request: PreviewShipmentsRequest
    ) -> PreviewShipmentsResult:
        total = 0
        for shipment in request.shipments:
            rate = await self._carrier_gateway.rate(RateRequest(shipment=shipment))
            total += rate.total_cost_cents
        return PreviewShipmentsResult(
            preview_id=f"preview_{uuid4()}",
            total_cost_cents=total,
            requires_confirmation=True,
            summary=PreviewShipmentsSummary(shipment_count=len(request.shipments)),
        )
