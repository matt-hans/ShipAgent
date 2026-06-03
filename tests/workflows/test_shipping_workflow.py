import pytest
from pydantic import ValidationError

from src.carriers.models import RateRequest, RateResult
from src.workflows.models import PreviewShipmentsRequest
from src.workflows.shipping import ShippingWorkflowService


class FakeCarrierGateway:
    def __init__(self) -> None:
        self.requests: list[RateRequest] = []

    async def rate(self, request: RateRequest) -> RateResult:
        self.requests.append(request)
        costs = [1000, 2500]
        return RateResult(
            carrier="UPS",
            total_cost_cents=costs[len(self.requests) - 1],
            raw={},
        )


@pytest.mark.asyncio
async def test_preview_shipments_returns_confirmation_ready_preview():
    gateway = FakeCarrierGateway()
    service = ShippingWorkflowService(carrier_gateway=gateway)
    shipments = [{"service": "03"}, {"service": "12"}]

    result = await service.preview_shipments(
        PreviewShipmentsRequest(
            tenant_id="tenant-1",
            order_batch_id="batch-1",
            shipments=shipments,
        )
    )

    assert len(gateway.requests) == 2
    assert all(isinstance(request, RateRequest) for request in gateway.requests)
    assert [request.shipment for request in gateway.requests] == shipments
    assert result.preview_id.startswith("preview_")
    assert result.total_cost_cents == 3500
    assert result.requires_confirmation is True
    assert result.summary.shipment_count == 2


def test_preview_shipments_requires_at_least_one_shipment():
    with pytest.raises(ValidationError):
        PreviewShipmentsRequest(
            tenant_id="tenant-1",
            order_batch_id="batch-1",
            shipments=[],
        )
