# tests/services/test_platform_models.py
"""Tests for platform contract models and error taxonomy."""
import pytest
from src.services.platform_models import (
    PlatformErrorCode,
    PlatformError,
    HealthReport,
    CapabilityManifest,
    AuthResult,
    OrderPage,
    TrackingWriteBackPayload,
    WriteBackResult,
    ActivationReport,
    PlatformConfig,
    PlatformSummary,
)


class TestPlatformErrorCode:
    def test_all_codes_are_strings(self):
        for code in PlatformErrorCode:
            assert isinstance(code.value, str)

    def test_required_codes_exist(self):
        required = {
            "AUTH_REQUIRED", "AUTH_EXPIRED", "RATE_LIMITED",
            "NOT_FOUND", "INVALID_ARGUMENT", "UPSTREAM_ERROR",
            "TRANSIENT", "PERMANENT",
        }
        actual = {c.value for c in PlatformErrorCode}
        assert required.issubset(actual)

    def test_retryable_codes(self):
        retryable = PlatformErrorCode.retryable_codes()
        assert PlatformErrorCode.TRANSIENT in retryable
        assert PlatformErrorCode.RATE_LIMITED in retryable
        assert PlatformErrorCode.UPSTREAM_ERROR in retryable
        assert PlatformErrorCode.PERMANENT not in retryable
        assert PlatformErrorCode.AUTH_EXPIRED not in retryable

    def test_trips_circuit_breaker(self):
        breaker_codes = PlatformErrorCode.circuit_breaker_codes()
        assert PlatformErrorCode.TRANSIENT in breaker_codes
        assert PlatformErrorCode.UPSTREAM_ERROR in breaker_codes
        assert PlatformErrorCode.RATE_LIMITED not in breaker_codes  # critical: rate limit != failure


class TestPlatformError:
    def test_from_dict(self):
        d = {
            "error_code": "RATE_LIMITED",
            "message": "Too many requests",
            "retry_after_seconds": 2,
            "provider_status": 429,
        }
        err = PlatformError.from_dict(d)
        assert err.error_code == PlatformErrorCode.RATE_LIMITED
        assert err.retry_after_seconds == 2

    def test_to_dict_roundtrip(self):
        err = PlatformError(
            error_code=PlatformErrorCode.TRANSIENT,
            message="timeout",
        )
        d = err.to_dict()
        assert d["error_code"] == "TRANSIENT"
        assert "request_id" not in d or d["request_id"] is None


class TestHealthReport:
    def test_contract_version_required(self):
        report = HealthReport(
            ok=True,
            platform_id="shopify",
            server_version="1.0.0",
            contract_version="1.0",
            api_reachable=True,
            auth_valid=True,
        )
        assert report.contract_version == "1.0"


class TestCapabilityManifest:
    def test_supports_tool(self):
        manifest = CapabilityManifest(
            platform_id="shopify",
            contract_version="1.0",
            supports=["orders.list", "orders.get", "tracking.write_back"],
            limits={"rate_limit_per_second": 2, "max_concurrency": 3},
            paging={"strategy": "cursor", "default_page_size": 50, "max_page_size": 250, "overlap_seconds": 300},
        )
        assert manifest.supports_tool("orders.list")
        assert not manifest.supports_tool("orders.delta")

    def test_get_rate_limit(self):
        manifest = CapabilityManifest(
            platform_id="test",
            contract_version="1.0",
            supports=[],
            limits={"rate_limit_per_second": 5, "max_concurrency": 2},
            paging={},
        )
        assert manifest.rate_limit_per_second == 5
        assert manifest.max_concurrency == 2

    def test_defaults_when_limits_missing(self):
        manifest = CapabilityManifest(
            platform_id="test",
            contract_version="1.0",
            supports=[],
            limits={},
            paging={},
        )
        assert manifest.rate_limit_per_second == 5  # default
        assert manifest.max_concurrency == 3  # default


class TestOrderPage:
    def test_has_more_when_next_cursor_present(self):
        page = OrderPage(items=[{"id": "1"}], next_cursor="abc", watermark="2026-01-01T00:00:00Z")
        assert page.has_more is True

    def test_no_more_when_next_cursor_none(self):
        page = OrderPage(items=[], next_cursor=None, watermark="2026-01-01T00:00:00Z")
        assert page.has_more is False


class TestPlatformConfig:
    def test_frozen(self):
        config = PlatformConfig(
            platform_id="shopify",
            display_name="Shopify",
            default_profile="primary",
            required_secret_keys=["SHOPIFY_ACCESS_TOKEN", "SHOPIFY_STORE_DOMAIN"],
            mcp_module="src.mcp.platforms.shopify.server",
            mcp_bundle_subcommand="mcp-shopify",
            contract_version="1.0",
            default_sync_overlap_seconds=300,
            enabled=True,
        )
        with pytest.raises(AttributeError):
            config.platform_id = "amazon"


class TestTrackingWriteBackPayload:
    def test_multiple_tracking_numbers(self):
        payload = TrackingWriteBackPayload(
            tracking_numbers=["1Z999AA10123456784", "1Z999AA10123456785"],
            carrier="UPS",
        )
        assert len(payload.tracking_numbers) == 2


class TestActivationReport:
    def test_summary(self):
        report = ActivationReport(
            platform_id="shopify",
            credential_ref="primary",
            mode="initial",
            total_imported=150,
            pages_fetched=3,
            watermark="2026-02-28T12:00:00Z",
            duration_seconds=4.5,
            warnings=[],
        )
        assert report.total_imported == 150
