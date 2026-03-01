# tests/services/test_batch_engine_writeback.py
"""Tests for platform-aware tracking write-back routing through PlatformGateway."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.batch_engine import BatchEngine


def _make_row(row_number: int, order_data: dict | None = None) -> MagicMock:
    """Build a fake JobRow with order_data."""
    row = MagicMock()
    row.row_number = row_number
    row.order_data = json.dumps(order_data) if order_data else None
    return row


def _make_shopify_order_data(order_id: str = "ORD-1") -> dict:
    """Build order_data dict for a Shopify row."""
    return {
        "order_id": order_id,
        "platform": "shopify",
        "credential_ref": "primary",
        "external_id": order_id,
    }


class TestWriteBackRoutesToCorrectPlatform:
    """Shopify rows should route write-back through PlatformGateway."""

    @pytest.mark.asyncio
    async def test_writeback_routes_to_correct_platform(self):
        """Platform rows call gateway.call_tool('tracking.write_back', ...)."""
        rows = [_make_row(1, _make_shopify_order_data("ORD-1"))]
        updates = {1: {"tracking_number": "1Z999", "shipped_at": "2026-02-28T12:00:00Z"}}

        mock_gateway = AsyncMock()
        mock_gateway.call_tool.return_value = {"ok": True}

        engine = BatchEngine.__new__(BatchEngine)
        result = await engine._write_back_platform(
            gateway=mock_gateway,
            updates=updates,
            rows=rows,
            capabilities_cache={
                ("shopify", "primary"): {"supports": ["tracking.write_back"]},
            },
        )

        assert result["success_count"] == 1
        assert result["failure_count"] == 0
        mock_gateway.call_tool.assert_called_once()
        call_args = mock_gateway.call_tool.call_args
        assert call_args[0][0] == "shopify"     # platform_id
        assert call_args[0][1] == "primary"      # credential_ref
        assert call_args[0][2] == "tracking.write_back"  # tool_name


class TestCapabilityFetchOncePerPlatform:
    """Capabilities should be fetched once per (platform, credential_ref) per run."""

    @pytest.mark.asyncio
    async def test_capability_fetch_once_per_platform_per_run(self):
        """5 shopify rows → 1 get_capabilities call, not 5."""
        rows = [
            _make_row(i, _make_shopify_order_data(f"ORD-{i}"))
            for i in range(1, 6)
        ]
        updates = {
            i: {"tracking_number": f"1Z{i:03d}", "shipped_at": "2026-02-28T12:00:00Z"}
            for i in range(1, 6)
        }

        mock_gateway = AsyncMock()
        mock_gateway.call_tool.side_effect = lambda pid, cref, tool, args: (
            {"supports": ["tracking.write_back"]} if tool == "platform.capabilities"
            else {"ok": True}
        )

        engine = BatchEngine.__new__(BatchEngine)
        caps_cache: dict = {}
        result = await engine._write_back_platform(
            gateway=mock_gateway,
            updates=updates,
            rows=rows,
            capabilities_cache=caps_cache,
        )

        assert result["success_count"] == 5
        # Should have called capabilities once + 5 write-back calls = 6 total
        cap_calls = [
            c for c in mock_gateway.call_tool.call_args_list
            if c[0][2] == "platform.capabilities"
        ]
        assert len(cap_calls) == 1
        # Cache should have the entry
        assert ("shopify", "primary") in caps_cache


class TestWriteBackSkippedWhenUnsupported:
    """Platform without tracking.write_back → no write-back call."""

    @pytest.mark.asyncio
    async def test_writeback_skipped_when_unsupported(self):
        """Platform missing tracking.write_back in capabilities → skip."""
        rows = [_make_row(1, _make_shopify_order_data("ORD-1"))]
        updates = {1: {"tracking_number": "1Z999", "shipped_at": "2026-02-28T12:00:00Z"}}

        mock_gateway = AsyncMock()
        mock_gateway.call_tool.return_value = {
            "supports": ["orders.list", "orders.get"],  # No tracking.write_back
        }

        engine = BatchEngine.__new__(BatchEngine)
        result = await engine._write_back_platform(
            gateway=mock_gateway,
            updates=updates,
            rows=rows,
            capabilities_cache={},
        )

        # Row should be skipped (not failed, not succeeded for write-back)
        assert result["success_count"] == 0
        assert result["failure_count"] == 0
        assert result["skipped_count"] == 1


class TestRateLimitedWriteBackDoesNotFailBatch:
    """Rate-limited write-back should not abort the entire batch."""

    @pytest.mark.asyncio
    async def test_rate_limited_writeback_does_not_fail_batch(self):
        """RATE_LIMITED on write-back counts as failure, doesn't raise."""
        from src.services.platform_models import PlatformError, PlatformErrorCode

        rows = [
            _make_row(1, _make_shopify_order_data("ORD-1")),
            _make_row(2, _make_shopify_order_data("ORD-2")),
        ]
        updates = {
            1: {"tracking_number": "1Z001", "shipped_at": "2026-02-28T12:00:00Z"},
            2: {"tracking_number": "1Z002", "shipped_at": "2026-02-28T12:00:00Z"},
        }

        call_count = 0

        async def mock_call_tool(pid, cref, tool, args):
            nonlocal call_count
            call_count += 1
            if tool == "tracking.write_back":
                if args.get("order_id") == "ORD-1":
                    raise PlatformError(
                        error_code=PlatformErrorCode.RATE_LIMITED,
                        message="Too many requests",
                    )
                return {"ok": True}
            return {"supports": ["tracking.write_back"]}

        mock_gateway = AsyncMock()
        mock_gateway.call_tool.side_effect = mock_call_tool

        engine = BatchEngine.__new__(BatchEngine)
        result = await engine._write_back_platform(
            gateway=mock_gateway,
            updates=updates,
            rows=rows,
            capabilities_cache={},
        )

        # First row failed (rate limited), second succeeded
        assert result["success_count"] == 1
        assert result["failure_count"] == 1
        assert len(result["errors"]) == 1
        assert result["errors"][0]["row_number"] == 1


class TestReadsFromOrderData:
    """Platform/credential_ref read from order_data, not from external source."""

    @pytest.mark.asyncio
    async def test_reads_platform_from_order_data(self):
        """Uses platform/credential_ref from order_data JSON."""
        order_data = {
            "order_id": "WOO-42",
            "platform": "woocommerce",
            "credential_ref": "store-eu",
            "external_id": "WOO-42",
        }
        rows = [_make_row(1, order_data)]
        updates = {1: {"tracking_number": "1Z999", "shipped_at": "2026-02-28T12:00:00Z"}}

        mock_gateway = AsyncMock()
        mock_gateway.call_tool.return_value = {"ok": True}

        engine = BatchEngine.__new__(BatchEngine)
        result = await engine._write_back_platform(
            gateway=mock_gateway,
            updates=updates,
            rows=rows,
            capabilities_cache={
                ("woocommerce", "store-eu"): {"supports": ["tracking.write_back"]},
            },
        )

        assert result["success_count"] == 1
        call_args = mock_gateway.call_tool.call_args
        assert call_args[0][0] == "woocommerce"
        assert call_args[0][1] == "store-eu"
