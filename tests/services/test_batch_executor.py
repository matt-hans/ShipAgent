"""Tests for shared batch execution service."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.batch_executor import execute_batch, get_shipper_for_job


class TestGetShipperForJob:
    """Tests for shipper resolution logic.

    get_shipper_for_job() is async (Shopify fallback requires MCP call),
    so all tests use async def + await.
    """

    @pytest.mark.asyncio
    async def test_uses_persisted_shipper_json(self):
        """Returns persisted shipper when job has shipper_json."""
        job = MagicMock()
        job.shipper_json = '{"name": "Acme Corp", "city": "LA"}'
        result = await get_shipper_for_job(job)
        assert result["name"] == "Acme Corp"

    @pytest.mark.asyncio
    async def test_falls_back_to_env_shipper(self, monkeypatch):
        """Falls back to env-based shipper when no shipper_json."""
        job = MagicMock()
        job.shipper_json = None
        monkeypatch.setenv("SHIPPER_NAME", "Env Corp")

        mock_gw = AsyncMock()
        mock_gw.get_source_info = AsyncMock(return_value={"source_type": "csv"})

        with patch(
            "src.services.gateway_provider.get_data_gateway",
            new_callable=AsyncMock,
            return_value=mock_gw,
        ):
            result = await get_shipper_for_job(job)
            # Should not raise; returns a dict
            assert isinstance(result, dict)
