from typing import Any

from pydantic import BaseModel


class RateRequest(BaseModel):
    shipment: dict[str, Any]


class RateResult(BaseModel):
    carrier: str
    total_cost_cents: int
    raw: dict[str, Any]
