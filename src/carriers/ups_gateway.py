from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from src.carriers.models import RateRequest, RateResult

_MISSING = object()


def _money_to_cents(value: Any) -> int:
    try:
        return int(
            Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100
        )
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid UPS monetary value: {value!r}") from exc


def _first_present(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return _MISSING


def _first_rated_shipment(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        for shipment in value:
            if isinstance(shipment, dict):
                return shipment
    return None


def _rated_shipment(raw: dict[str, Any]) -> dict[str, Any] | None:
    rate_response = raw.get("RateResponse")
    if isinstance(rate_response, dict):
        shipment = _first_rated_shipment(rate_response.get("RatedShipment"))
        if shipment is not None:
            return shipment
    return _first_rated_shipment(raw.get("RatedShipment"))


def _total_charge_value(charges: Any) -> Any:
    if not isinstance(charges, dict):
        return _MISSING
    return _first_present(charges, ("monetaryValue", "amount", "MonetaryValue"))


def _rate_monetary_value(raw: dict[str, Any]) -> Any:
    normalized = _total_charge_value(raw.get("totalCharges"))
    if normalized is not _MISSING:
        return normalized

    shipment = _rated_shipment(raw)
    if shipment is None:
        raise ValueError("UPS rate response did not include a monetary value")

    negotiated = shipment.get("NegotiatedRateCharges", {}).get("TotalCharge", {})
    negotiated_value = _total_charge_value(negotiated)
    if negotiated_value is not _MISSING:
        return negotiated_value

    published_value = _total_charge_value(shipment.get("TotalCharges"))
    if published_value is not _MISSING:
        return published_value

    raise ValueError("UPS rate response did not include a monetary value")


class UPSCarrierGateway:
    """Carrier-neutral wrapper around the internal UPS MCP client."""

    def __init__(self, ups_client: Any) -> None:
        self._ups_client = ups_client

    async def rate(self, request: RateRequest) -> RateResult:
        get_rate = getattr(self._ups_client, "get_rate", None)
        if callable(get_rate):
            raw = await get_rate(request_body=request.shipment)
        else:
            raw = await self._ups_client.rate_shipment(request.shipment)

        return RateResult(
            carrier="UPS",
            total_cost_cents=_money_to_cents(_rate_monetary_value(raw)),
            raw=raw,
        )
