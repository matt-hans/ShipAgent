from typing import Any

from pydantic import BaseModel, Field


class PreviewShipmentsRequest(BaseModel):
    tenant_id: str
    order_batch_id: str
    shipments: list[dict[str, Any]] = Field(min_length=1)


class PreviewShipmentsSummary(BaseModel):
    shipment_count: int


class PreviewShipmentsResult(BaseModel):
    preview_id: str
    total_cost_cents: int
    requires_confirmation: bool
    summary: PreviewShipmentsSummary
