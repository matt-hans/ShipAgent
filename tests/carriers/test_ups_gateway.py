import pytest

from src.carriers.models import RateRequest
from src.carriers.ups_gateway import UPSCarrierGateway


class FakeRateShipmentClient:
    async def rate_shipment(self, payload):
        return {"RatedShipment": {"TotalCharges": {"MonetaryValue": "12.34"}}}


@pytest.mark.asyncio
async def test_rate_normalizes_ups_response():
    gateway = UPSCarrierGateway(FakeRateShipmentClient())
    result = await gateway.rate(RateRequest(shipment={"service": "03"}))

    assert result.total_cost_cents == 1234
    assert result.carrier == "UPS"


@pytest.mark.asyncio
async def test_rate_uses_get_rate_client_when_available():
    class FakeGetRateClient:
        def __init__(self):
            self.request_body = None

        async def get_rate(self, request_body):
            self.request_body = request_body
            return {
                "success": True,
                "totalCharges": {
                    "monetaryValue": "12.50",
                    "amount": "12.50",
                    "currencyCode": "USD",
                },
            }

    client = FakeGetRateClient()
    gateway = UPSCarrierGateway(client)
    shipment = {"service": "03"}

    result = await gateway.rate(RateRequest(shipment=shipment))

    assert client.request_body == shipment
    assert result.total_cost_cents == 1250
    assert result.carrier == "UPS"


@pytest.mark.asyncio
async def test_rate_uses_normalized_amount_when_monetary_value_missing():
    class FakeGetRateClient:
        async def get_rate(self, request_body):
            return {
                "success": True,
                "totalCharges": {
                    "amount": "13.25",
                    "currencyCode": "USD",
                },
            }

    gateway = UPSCarrierGateway(FakeGetRateClient())

    result = await gateway.rate(RateRequest(shipment={"service": "03"}))

    assert result.total_cost_cents == 1325


@pytest.mark.asyncio
async def test_rate_normalizes_rate_response_rated_shipment_dict():
    class FakeRateShipmentClient:
        async def rate_shipment(self, payload):
            return {
                "RateResponse": {
                    "RatedShipment": {
                        "TotalCharges": {
                            "MonetaryValue": "14.75",
                            "CurrencyCode": "USD",
                        },
                    },
                },
            }

    gateway = UPSCarrierGateway(FakeRateShipmentClient())

    result = await gateway.rate(RateRequest(shipment={"service": "03"}))

    assert result.total_cost_cents == 1475


@pytest.mark.asyncio
async def test_rate_normalizes_rate_response_rated_shipment_list_prefers_negotiated():
    class FakeRateShipmentClient:
        async def rate_shipment(self, payload):
            return {
                "RateResponse": {
                    "RatedShipment": [
                        {
                            "TotalCharges": {
                                "MonetaryValue": "99.99",
                                "CurrencyCode": "USD",
                            },
                            "NegotiatedRateCharges": {
                                "TotalCharge": {
                                    "MonetaryValue": "8.76",
                                    "CurrencyCode": "USD",
                                },
                            },
                        },
                    ],
                },
            }

    gateway = UPSCarrierGateway(FakeRateShipmentClient())

    result = await gateway.rate(RateRequest(shipment={"service": "03"}))

    assert result.total_cost_cents == 876


@pytest.mark.asyncio
async def test_rate_rounds_money_half_up():
    class FakeGetRateClient:
        async def get_rate(self, request_body):
            return {
                "success": True,
                "totalCharges": {
                    "monetaryValue": "12.345",
                    "currencyCode": "USD",
                },
            }

    gateway = UPSCarrierGateway(FakeGetRateClient())

    result = await gateway.rate(RateRequest(shipment={"service": "03"}))

    assert result.total_cost_cents == 1235


@pytest.mark.asyncio
async def test_rate_accepts_explicit_normalized_zero():
    class FakeGetRateClient:
        async def get_rate(self, request_body):
            return {
                "success": True,
                "totalCharges": {
                    "monetaryValue": "0",
                    "currencyCode": "USD",
                },
            }

    gateway = UPSCarrierGateway(FakeGetRateClient())

    result = await gateway.rate(RateRequest(shipment={"service": "03"}))

    assert result.total_cost_cents == 0


@pytest.mark.asyncio
async def test_rate_raises_when_monetary_value_is_missing():
    class FakeGetRateClient:
        async def get_rate(self, request_body):
            return {"success": True, "totalCharges": {"currencyCode": "USD"}}

    gateway = UPSCarrierGateway(FakeGetRateClient())

    with pytest.raises(ValueError, match="monetary value"):
        await gateway.rate(RateRequest(shipment={"service": "03"}))


@pytest.mark.asyncio
async def test_rate_raises_when_monetary_value_is_invalid():
    class FakeGetRateClient:
        async def get_rate(self, request_body):
            return {
                "success": True,
                "totalCharges": {
                    "monetaryValue": "not-money",
                    "currencyCode": "USD",
                },
            }

    gateway = UPSCarrierGateway(FakeGetRateClient())

    with pytest.raises(ValueError, match="Invalid UPS monetary value"):
        await gateway.rate(RateRequest(shipment={"service": "03"}))
