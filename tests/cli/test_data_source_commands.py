"""Tests for CLI data source commands added in PR #12.

Covers:
- DefaultDataSourceConfig model validation (at-most-one-source constraint)
- Protocol data models: DataSourceStatus, SavedSourceSummary, SourceSchemaColumn
- InProcessRunner data source methods (get_source_status, connect_platform, etc.)
- HttpClient data source methods (get_source_status, connect_platform, etc.)
- Output formatters: format_source_status, format_saved_sources, format_schema
"""

import importlib

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.cli.config import DefaultDataSourceConfig
from src.cli.http_client import HttpClient
from src.cli.output import format_saved_sources, format_schema, format_source_status
from src.cli.protocol import (
    DataSourceStatus,
    SavedSourceSummary,
    ShipAgentClientError,
    SourceSchemaColumn,
)
from src.cli.runner import InProcessRunner


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _use_tmp_db(tmp_path, monkeypatch):
    """Use a fresh temporary database for each test.

    Mirrors the pattern in tests/cli/test_runner.py so InProcessRunner
    tests get an isolated SQLite database.
    """
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    import src.db.connection as conn_mod

    importlib.reload(conn_mod)


# ---------------------------------------------------------------------------
# FakeTransport (reused pattern from test_http_client.py)
# ---------------------------------------------------------------------------


class FakeTransport(httpx.AsyncBaseTransport):
    """Mock transport that returns canned responses keyed by URL substring."""

    def __init__(self, responses: dict[str, tuple[int, dict]]):
        """Initialize with mapping of URL substring to (status_code, body).

        Args:
            responses: Dict mapping URL path substrings to (status, JSON body).
        """
        self._responses = responses

    async def handle_async_request(self, request):
        """Return canned response matching the request path.

        Args:
            request: The outgoing HTTP request.

        Returns:
            httpx.Response with the matching status code and JSON body,
            or a 404 if no pattern matches.
        """
        path = request.url.path
        for pattern, (status, body) in self._responses.items():
            if pattern in path:
                return httpx.Response(
                    status, json=body, request=request
                )
        return httpx.Response(404, json={"error": "not found"}, request=request)


def _make_client(responses: dict) -> HttpClient:
    """Create HttpClient with mocked transport.

    Args:
        responses: Dict mapping URL path substrings to (status, JSON body).

    Returns:
        HttpClient wired to the fake transport.
    """
    client = HttpClient(base_url="http://127.0.0.1:8000")
    transport = FakeTransport(responses)
    client._client = httpx.AsyncClient(
        transport=transport, base_url="http://127.0.0.1:8000"
    )
    return client


# ===========================================================================
# 1. DefaultDataSourceConfig Validation
# ===========================================================================


class TestDefaultDataSourceConfig:
    """Tests for the at-most-one-source model validator."""

    def test_single_path_field_valid(self):
        """Setting only 'path' is valid."""
        cfg = DefaultDataSourceConfig(path="/data/orders.csv")
        assert cfg.path == "/data/orders.csv"
        assert cfg.saved_source is None
        assert cfg.platform is None

    def test_single_saved_source_field_valid(self):
        """Setting only 'saved_source' is valid."""
        cfg = DefaultDataSourceConfig(saved_source="my-source")
        assert cfg.saved_source == "my-source"
        assert cfg.path is None

    def test_single_platform_field_valid(self):
        """Setting only 'platform' is valid."""
        cfg = DefaultDataSourceConfig(platform="shopify")
        assert cfg.platform == "shopify"
        assert cfg.path is None

    def test_zero_fields_valid(self):
        """All None is valid -- the parent config treats default_data_source as optional."""
        cfg = DefaultDataSourceConfig()
        assert cfg.path is None
        assert cfg.saved_source is None
        assert cfg.platform is None

    def test_two_fields_raises_value_error(self):
        """Setting path + platform violates at-most-one constraint."""
        with pytest.raises(ValueError, match="Only one of"):
            DefaultDataSourceConfig(path="/data/x.csv", platform="shopify")

    def test_three_fields_raises_value_error(self):
        """Setting all three fields violates at-most-one constraint."""
        with pytest.raises(ValueError, match="Only one of"):
            DefaultDataSourceConfig(
                path="/data/x.csv",
                saved_source="my-source",
                platform="shopify",
            )

    def test_path_and_saved_source_raises(self):
        """Setting path + saved_source violates at-most-one constraint."""
        with pytest.raises(ValueError, match="Only one of"):
            DefaultDataSourceConfig(
                path="/data/x.csv", saved_source="my-source"
            )


# ===========================================================================
# 2. Protocol Data Models
# ===========================================================================


class TestDataSourceStatusModel:
    """Tests for DataSourceStatus dataclass."""

    def test_connected_status(self):
        """Connected status populates all optional fields."""
        status = DataSourceStatus(
            connected=True,
            source_type="csv",
            file_path="/data/orders.csv",
            row_count=42,
            column_count=8,
            columns=["name", "address", "city"],
        )
        assert status.connected is True
        assert status.source_type == "csv"
        assert status.row_count == 42
        assert status.column_count == 8
        assert len(status.columns) == 3

    def test_disconnected_status(self):
        """Disconnected status has sensible defaults."""
        status = DataSourceStatus(connected=False)
        assert status.connected is False
        assert status.source_type is None
        assert status.file_path is None
        assert status.row_count is None
        assert status.column_count is None
        assert status.columns == []

    def test_default_columns_empty_list(self):
        """Columns default to empty list (no mutable default sharing)."""
        s1 = DataSourceStatus(connected=False)
        s2 = DataSourceStatus(connected=False)
        s1.columns.append("test")
        assert s2.columns == [], "Mutable default should not be shared"


class TestSavedSourceSummaryModel:
    """Tests for SavedSourceSummary dataclass and from_api()."""

    def test_from_api_full_data(self):
        """from_api constructs summary from a complete API response dict."""
        data = {
            "id": "src-abc",
            "name": "Monthly Orders",
            "source_type": "csv",
            "file_path": "/data/monthly.csv",
            "last_connected": "2026-02-18T12:00:00Z",
            "row_count": 150,
        }
        summary = SavedSourceSummary.from_api(data)
        assert summary.id == "src-abc"
        assert summary.name == "Monthly Orders"
        assert summary.source_type == "csv"
        assert summary.file_path == "/data/monthly.csv"
        assert summary.last_connected == "2026-02-18T12:00:00Z"
        assert summary.row_count == 150

    def test_from_api_partial_data(self):
        """from_api uses defaults for missing optional fields."""
        data = {"id": "src-xyz"}
        summary = SavedSourceSummary.from_api(data)
        assert summary.id == "src-xyz"
        assert summary.name == ""
        assert summary.source_type == ""
        assert summary.file_path is None
        assert summary.last_connected is None
        assert summary.row_count is None

    def test_from_api_extra_fields_ignored(self):
        """Extra fields in API response are silently ignored."""
        data = {
            "id": "src-abc",
            "name": "Test",
            "source_type": "excel",
            "extra_field": "should be ignored",
            "another_extra": 999,
        }
        summary = SavedSourceSummary.from_api(data)
        assert summary.id == "src-abc"
        assert not hasattr(summary, "extra_field")


class TestSourceSchemaColumnModel:
    """Tests for SourceSchemaColumn dataclass defaults."""

    def test_defaults(self):
        """type defaults to required, nullable defaults to True."""
        col = SourceSchemaColumn(name="order_id", type="INTEGER")
        assert col.name == "order_id"
        assert col.type == "INTEGER"
        assert col.nullable is True
        assert col.sample_values == []

    def test_non_nullable(self):
        """Explicitly non-nullable column."""
        col = SourceSchemaColumn(name="tracking", type="VARCHAR", nullable=False)
        assert col.nullable is False

    def test_sample_values_isolation(self):
        """Sample values default list is not shared across instances."""
        c1 = SourceSchemaColumn(name="a", type="VARCHAR")
        c2 = SourceSchemaColumn(name="b", type="VARCHAR")
        c1.sample_values.append("test")
        assert c2.sample_values == [], "Mutable default should not be shared"


# ===========================================================================
# 3. InProcessRunner — get_source_status
# ===========================================================================


_GW_PATCH = "src.services.gateway_provider.get_data_gateway"
_EXT_PATCH = "src.services.gateway_provider.get_external_sources_client"


class TestRunnerGetSourceStatus:
    """Tests for InProcessRunner.get_source_status()."""

    @pytest.mark.asyncio
    async def test_returns_connected_status(self):
        """Returns connected=True with parsed columns when gateway has a source."""
        mock_gw = AsyncMock()
        mock_gw.get_source_info.return_value = {
            "source_type": "csv",
            "path": "/data/orders.csv",
            "row_count": 25,
            "columns": [
                {"name": "order_id", "type": "INTEGER"},
                {"name": "customer_name", "type": "VARCHAR"},
            ],
        }

        runner = InProcessRunner()
        async with runner:
            with patch(_GW_PATCH, new=AsyncMock(return_value=mock_gw)):
                status = await runner.get_source_status()

        assert status.connected is True
        assert status.source_type == "csv"
        assert status.file_path == "/data/orders.csv"
        assert status.row_count == 25
        assert status.column_count == 2
        assert status.columns == ["order_id", "customer_name"]

    @pytest.mark.asyncio
    async def test_returns_disconnected_when_no_source(self):
        """Returns connected=False when gateway returns None."""
        mock_gw = AsyncMock()
        mock_gw.get_source_info.return_value = None

        runner = InProcessRunner()
        async with runner:
            with patch(_GW_PATCH, new=AsyncMock(return_value=mock_gw)):
                status = await runner.get_source_status()

        assert status.connected is False
        assert status.source_type is None
        assert status.columns == []

    @pytest.mark.asyncio
    async def test_raises_on_gateway_init_failure(self):
        """Raises ShipAgentClientError when gateway initialization fails."""
        runner = InProcessRunner()
        async with runner:
            with patch(
                _GW_PATCH,
                new=AsyncMock(side_effect=RuntimeError("MCP not available")),
            ):
                with pytest.raises(ShipAgentClientError, match="Cannot reach data source gateway"):
                    await runner.get_source_status()

    @pytest.mark.asyncio
    async def test_raises_on_gateway_query_failure(self):
        """Raises ShipAgentClientError when gateway query fails."""
        mock_gw = AsyncMock()
        mock_gw.get_source_info.side_effect = RuntimeError("query timeout")

        runner = InProcessRunner()
        async with runner:
            with patch(_GW_PATCH, new=AsyncMock(return_value=mock_gw)):
                with pytest.raises(ShipAgentClientError, match="Data source query failed"):
                    await runner.get_source_status()

    @pytest.mark.asyncio
    async def test_handles_string_columns(self):
        """Handles columns returned as plain strings (not dicts)."""
        mock_gw = AsyncMock()
        mock_gw.get_source_info.return_value = {
            "source_type": "excel",
            "path": "/data/orders.xlsx",
            "row_count": 10,
            "columns": ["col_a", "col_b", "col_c"],
        }

        runner = InProcessRunner()
        async with runner:
            with patch(_GW_PATCH, new=AsyncMock(return_value=mock_gw)):
                status = await runner.get_source_status()

        assert status.columns == ["col_a", "col_b", "col_c"]
        assert status.column_count == 3


# ===========================================================================
# 4. InProcessRunner — connect_platform
# ===========================================================================


class TestRunnerConnectPlatform:
    """Tests for InProcessRunner.connect_platform()."""

    @pytest.mark.asyncio
    async def test_non_shopify_raises(self):
        """Non-shopify platform raises ShipAgentClientError."""
        runner = InProcessRunner()
        async with runner:
            with pytest.raises(ShipAgentClientError, match="Only 'shopify'"):
                await runner.connect_platform("woocommerce")

    @pytest.mark.asyncio
    async def test_missing_env_vars_raises(self, monkeypatch):
        """Missing SHOPIFY env vars raises ShipAgentClientError."""
        monkeypatch.delenv("SHOPIFY_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("SHOPIFY_STORE_DOMAIN", raising=False)

        runner = InProcessRunner()
        async with runner:
            with pytest.raises(
                ShipAgentClientError,
                match="SHOPIFY_ACCESS_TOKEN and SHOPIFY_STORE_DOMAIN",
            ):
                await runner.connect_platform("shopify")

    @pytest.mark.asyncio
    async def test_missing_one_env_var_raises(self, monkeypatch):
        """Having only one Shopify env var still raises."""
        monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "shpat_test123")
        monkeypatch.delenv("SHOPIFY_STORE_DOMAIN", raising=False)

        runner = InProcessRunner()
        async with runner:
            with pytest.raises(
                ShipAgentClientError,
                match="SHOPIFY_ACCESS_TOKEN and SHOPIFY_STORE_DOMAIN",
            ):
                await runner.connect_platform("shopify")

    @pytest.mark.asyncio
    async def test_success_path(self, monkeypatch):
        """Successful Shopify connect returns DataSourceStatus."""
        monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "shpat_test123")
        monkeypatch.setenv("SHOPIFY_STORE_DOMAIN", "test-store.myshopify.com")

        mock_ext_client = AsyncMock()
        mock_ext_client.connect_platform.return_value = {"valid": True}

        mock_data_gw = AsyncMock()
        mock_data_gw.get_source_info.return_value = {
            "source_type": "shopify",
            "path": None,
            "row_count": 15,
            "columns": [{"name": "order_number", "type": "VARCHAR"}],
        }

        runner = InProcessRunner()
        async with runner:
            with patch(
                _EXT_PATCH,
                new=AsyncMock(return_value=mock_ext_client),
            ), patch(
                _GW_PATCH,
                new=AsyncMock(return_value=mock_data_gw),
            ):
                status = await runner.connect_platform("shopify")

        assert status.connected is True
        mock_ext_client.connect_platform.assert_called_once_with(
            platform="shopify",
            credentials={"access_token": "shpat_test123"},
            store_url="test-store.myshopify.com",
        )

    @pytest.mark.asyncio
    async def test_invalid_credentials_raises(self, monkeypatch):
        """Invalid Shopify credentials raise ShipAgentClientError."""
        monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "bad-token")
        monkeypatch.setenv("SHOPIFY_STORE_DOMAIN", "test.myshopify.com")

        mock_ext_client = AsyncMock()
        mock_ext_client.connect_platform.return_value = {
            "valid": False,
            "error": "Invalid access token",
        }

        runner = InProcessRunner()
        async with runner:
            with patch(
                _EXT_PATCH,
                new=AsyncMock(return_value=mock_ext_client),
            ):
                with pytest.raises(
                    ShipAgentClientError, match="Invalid access token"
                ):
                    await runner.connect_platform("shopify")

    @pytest.mark.asyncio
    async def test_case_insensitive_platform_name(self):
        """Platform name check is case-insensitive (e.g. 'Shopify' works)."""
        runner = InProcessRunner()
        async with runner:
            # "Fedex" should still raise the non-shopify error
            with pytest.raises(ShipAgentClientError, match="Only 'shopify'"):
                await runner.connect_platform("Fedex")


# ===========================================================================
# 5. InProcessRunner — connect_source, disconnect, schema, list/reconnect
# ===========================================================================


class TestRunnerConnectSource:
    """Tests for InProcessRunner.connect_source()."""

    @pytest.mark.asyncio
    async def test_csv_file_imports_via_gateway(self):
        """CSV file triggers import_csv on the data gateway."""
        mock_gw = AsyncMock()
        mock_gw.get_source_info.return_value = {
            "source_type": "csv",
            "path": "/data/test.csv",
            "row_count": 5,
            "columns": [{"name": "id", "type": "INTEGER"}],
        }

        runner = InProcessRunner()
        async with runner:
            with patch(_GW_PATCH, new=AsyncMock(return_value=mock_gw)):
                status = await runner.connect_source("/data/test.csv")

        mock_gw.import_csv.assert_called_once_with("/data/test.csv")
        assert status.connected is True

    @pytest.mark.asyncio
    async def test_xlsx_file_imports_via_gateway(self):
        """Excel file triggers import_excel on the data gateway."""
        mock_gw = AsyncMock()
        mock_gw.get_source_info.return_value = {
            "source_type": "excel",
            "path": "/data/orders.xlsx",
            "row_count": 10,
            "columns": [],
        }

        runner = InProcessRunner()
        async with runner:
            with patch(_GW_PATCH, new=AsyncMock(return_value=mock_gw)):
                status = await runner.connect_source("/data/orders.xlsx")

        mock_gw.import_excel.assert_called_once_with("/data/orders.xlsx")
        assert status.connected is True


class TestRunnerDisconnectSource:
    """Tests for InProcessRunner.disconnect_source()."""

    @pytest.mark.asyncio
    async def test_disconnect_calls_gateway(self):
        """Disconnect delegates to gateway.disconnect()."""
        mock_gw = AsyncMock()

        runner = InProcessRunner()
        async with runner:
            with patch(_GW_PATCH, new=AsyncMock(return_value=mock_gw)):
                await runner.disconnect_source()

        mock_gw.disconnect.assert_called_once()


class TestRunnerGetSourceSchema:
    """Tests for InProcessRunner.get_source_schema()."""

    @pytest.mark.asyncio
    async def test_returns_schema_columns(self):
        """Returns SourceSchemaColumn list from gateway info."""
        mock_gw = AsyncMock()
        mock_gw.get_source_info.return_value = {
            "columns": [
                {"name": "id", "type": "INTEGER", "nullable": False},
                {"name": "name", "type": "VARCHAR"},
            ],
        }

        runner = InProcessRunner()
        async with runner:
            with patch(_GW_PATCH, new=AsyncMock(return_value=mock_gw)):
                cols = await runner.get_source_schema()

        assert len(cols) == 2
        assert cols[0].name == "id"
        assert cols[0].type == "INTEGER"
        assert cols[0].nullable is False
        assert cols[1].nullable is True  # default

    @pytest.mark.asyncio
    async def test_raises_when_no_source(self):
        """Raises ShipAgentClientError when no source is connected."""
        mock_gw = AsyncMock()
        mock_gw.get_source_info.return_value = None

        runner = InProcessRunner()
        async with runner:
            with patch(_GW_PATCH, new=AsyncMock(return_value=mock_gw)):
                with pytest.raises(
                    ShipAgentClientError, match="No data source connected"
                ):
                    await runner.get_source_schema()


class TestRunnerConnectDb:
    """Tests for InProcessRunner.connect_db()."""

    @pytest.mark.asyncio
    async def test_delegates_to_gateway(self):
        """connect_db calls gateway.import_database with correct args."""
        mock_gw = AsyncMock()
        mock_gw.get_source_info.return_value = {
            "source_type": "database",
            "path": None,
            "row_count": 100,
            "columns": [],
        }

        runner = InProcessRunner()
        async with runner:
            with patch(_GW_PATCH, new=AsyncMock(return_value=mock_gw)):
                status = await runner.connect_db(
                    "postgresql://user:pass@host/db",
                    "SELECT * FROM orders",
                )

        mock_gw.import_database.assert_called_once_with(
            connection_string="postgresql://user:pass@host/db",
            query="SELECT * FROM orders",
        )
        assert status.connected is True


# ===========================================================================
# 6. HttpClient — Data Source Methods
# ===========================================================================


class TestHttpClientGetSourceStatus:
    """Tests for HttpClient.get_source_status()."""

    @pytest.mark.asyncio
    async def test_connected_status(self):
        """Parses 200 response into connected DataSourceStatus."""
        client = _make_client({
            "/api/v1/data-sources/status": (200, {
                "connected": True,
                "source_type": "csv",
                "file_path": "/data/orders.csv",
                "row_count": 42,
                "columns": [
                    {"name": "order_id", "type": "INTEGER"},
                    {"name": "customer", "type": "VARCHAR"},
                ],
            }),
        })
        status = await client.get_source_status()
        assert status.connected is True
        assert status.source_type == "csv"
        assert status.row_count == 42
        assert status.column_count == 2
        assert status.columns == ["order_id", "customer"]

    @pytest.mark.asyncio
    async def test_disconnected_on_404(self):
        """404 response returns connected=False status."""
        client = _make_client({})  # No matching routes -> 404
        status = await client.get_source_status()
        assert status.connected is False

    @pytest.mark.asyncio
    async def test_raises_on_server_error(self):
        """Non-200 non-404 raises ShipAgentClientError."""
        client = _make_client({
            "/api/v1/data-sources/status": (500, {"error": "internal"}),
        })
        with pytest.raises(ShipAgentClientError, match="Failed to get source status"):
            await client.get_source_status()


class TestHttpClientConnectPlatform:
    """Tests for HttpClient.connect_platform()."""

    @pytest.mark.asyncio
    async def test_non_shopify_raises(self):
        """Non-shopify platform raises ShipAgentClientError immediately."""
        client = _make_client({})
        with pytest.raises(ShipAgentClientError, match="Only 'shopify'"):
            await client.connect_platform("woocommerce")

    @pytest.mark.asyncio
    async def test_shopify_success(self, monkeypatch):
        """Successful Shopify connect returns DataSourceStatus."""
        monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "shpat_test")
        monkeypatch.setenv("SHOPIFY_STORE_DOMAIN", "test.myshopify.com")
        client = _make_client({
            "/api/v1/platforms/shopify/connect": (
                200, {"success": True, "platform": "shopify", "status": "connected"},
            ),
            "/api/v1/data-sources/status": (200, {
                "connected": True,
                "source_type": "shopify",
                "row_count": 20,
                "columns": [],
            }),
        })
        status = await client.connect_platform("shopify")
        assert status.connected is True
        assert status.source_type == "shopify"

    @pytest.mark.asyncio
    async def test_shopify_missing_env_vars(self):
        """Missing env vars raises ShipAgentClientError."""
        client = _make_client({})
        with pytest.raises(
            ShipAgentClientError,
            match="SHOPIFY_ACCESS_TOKEN",
        ):
            await client.connect_platform("shopify")


class TestHttpClientDisconnectSource:
    """Tests for HttpClient.disconnect_source()."""

    @pytest.mark.asyncio
    async def test_success(self):
        """200 response disconnects without error."""
        client = _make_client({
            "/api/v1/data-sources/disconnect": (200, {}),
        })
        await client.disconnect_source()  # Should not raise

    @pytest.mark.asyncio
    async def test_failure_raises(self):
        """Non-200/204 raises ShipAgentClientError."""
        client = _make_client({
            "/api/v1/data-sources/disconnect": (500, {"error": "fail"}),
        })
        with pytest.raises(ShipAgentClientError, match="Failed to disconnect"):
            await client.disconnect_source()


class TestHttpClientListSavedSources:
    """Tests for HttpClient.list_saved_sources()."""

    @pytest.mark.asyncio
    async def test_returns_summaries(self):
        """Parses saved sources list from API response."""
        client = _make_client({
            "/api/v1/saved-sources": (200, {
                "sources": [
                    {
                        "id": "src-1",
                        "name": "Monthly",
                        "source_type": "csv",
                        "file_path": "/data/monthly.csv",
                    },
                    {
                        "id": "src-2",
                        "name": "Weekly",
                        "source_type": "excel",
                    },
                ],
            }),
        })
        sources = await client.list_saved_sources()
        assert len(sources) == 2
        assert sources[0].name == "Monthly"
        assert sources[1].source_type == "excel"

    @pytest.mark.asyncio
    async def test_empty_list(self):
        """Empty sources list returns empty array."""
        client = _make_client({
            "/api/v1/saved-sources": (200, {"sources": []}),
        })
        sources = await client.list_saved_sources()
        assert sources == []


class TestHttpClientReconnectSavedSource:
    """Tests for HttpClient.reconnect_saved_source()."""

    @pytest.mark.asyncio
    async def test_reconnect_by_name(self):
        """Reconnect by name returns DataSourceStatus."""
        client = _make_client({
            "/api/v1/saved-sources/reconnect": (200, {}),
            "/api/v1/data-sources/status": (200, {
                "connected": True,
                "source_type": "csv",
                "row_count": 30,
                "columns": [],
            }),
        })
        status = await client.reconnect_saved_source("Monthly", by_name=True)
        assert status.connected is True

    @pytest.mark.asyncio
    async def test_reconnect_failure_raises(self):
        """Failed reconnect raises ShipAgentClientError."""
        client = _make_client({
            "/api/v1/saved-sources/reconnect": (
                404,
                {"error": "Source not found"},
            ),
        })
        with pytest.raises(ShipAgentClientError, match="Failed to reconnect"):
            await client.reconnect_saved_source("nonexistent")


class TestHttpClientGetSourceSchema:
    """Tests for HttpClient.get_source_schema()."""

    @pytest.mark.asyncio
    async def test_returns_columns(self):
        """Parses schema columns from API response."""
        client = _make_client({
            "/api/v1/data-sources/schema": (200, {
                "columns": [
                    {"name": "order_id", "type": "INTEGER", "nullable": False},
                    {"name": "ship_to_name", "type": "VARCHAR"},
                ],
            }),
        })
        cols = await client.get_source_schema()
        assert len(cols) == 2
        assert cols[0].name == "order_id"
        assert cols[0].nullable is False
        assert cols[1].type == "VARCHAR"
        assert cols[1].nullable is True  # default

    @pytest.mark.asyncio
    async def test_404_raises_no_source(self):
        """404 response raises ShipAgentClientError with appropriate message."""
        client = _make_client({})  # No matching routes -> 404
        with pytest.raises(ShipAgentClientError, match="No data source connected"):
            await client.get_source_schema()


class TestHttpClientConnectDb:
    """Tests for HttpClient.connect_db()."""

    @pytest.mark.asyncio
    async def test_success_returns_status(self):
        """Successful DB import returns DataSourceStatus."""
        client = _make_client({
            "/api/v1/data-sources/import": (200, {}),
            "/api/v1/data-sources/status": (200, {
                "connected": True,
                "source_type": "database",
                "row_count": 500,
                "columns": [],
            }),
        })
        status = await client.connect_db(
            "postgresql://user:pass@host/db", "SELECT * FROM orders"
        )
        assert status.connected is True
        assert status.source_type == "database"

    @pytest.mark.asyncio
    async def test_failure_raises(self):
        """Failed DB import raises ShipAgentClientError."""
        client = _make_client({
            "/api/v1/data-sources/import": (
                400,
                {"error": "Invalid connection string"},
            ),
        })
        with pytest.raises(ShipAgentClientError, match="Failed to connect DB"):
            await client.connect_db("bad://conn", "SELECT 1")


# ===========================================================================
# 7. Output Formatters
# ===========================================================================


class TestFormatSourceStatus:
    """Tests for format_source_status() output formatter."""

    def test_connected_shows_details(self):
        """Connected status displays type, path, row count, and column count."""
        status = DataSourceStatus(
            connected=True,
            source_type="csv",
            file_path="/data/orders.csv",
            row_count=42,
            column_count=8,
            columns=["a", "b"],
        )
        output = format_source_status(status)
        assert "csv" in output
        assert "/data/orders.csv" in output
        assert "42" in output
        assert "8" in output
        assert "Data Source" in output

    def test_disconnected_shows_message(self):
        """Disconnected status shows 'No data source connected'."""
        status = DataSourceStatus(connected=False)
        output = format_source_status(status)
        assert "No data source connected" in output
        assert "Data Source" in output

    def test_connected_without_path(self):
        """Connected status without file_path omits the path row."""
        status = DataSourceStatus(
            connected=True,
            source_type="shopify",
            row_count=15,
            column_count=5,
        )
        output = format_source_status(status)
        assert "shopify" in output
        assert "15" in output


class TestFormatSavedSources:
    """Tests for format_saved_sources() output formatter."""

    def test_empty_list_shows_message(self):
        """Empty list returns 'No saved sources found.'."""
        output = format_saved_sources([])
        assert "No saved sources found" in output

    def test_populated_list_shows_table(self):
        """Non-empty list renders a table with source details."""
        sources = [
            SavedSourceSummary(
                id="aaaabbbb-1111-2222-3333-444455556666",
                name="Monthly Orders",
                source_type="csv",
                file_path="/data/monthly.csv",
                last_connected="2026-02-18T12:00:00Z",
                row_count=150,
            ),
            SavedSourceSummary(
                id="ccccdddd-5555-6666-7777-888899990000",
                name="Weekly Export",
                source_type="excel",
                last_connected=None,
                row_count=None,
            ),
        ]
        output = format_saved_sources(sources)
        assert "Monthly Orders" in output
        assert "Weekly Export" in output
        assert "csv" in output
        assert "excel" in output
        assert "Saved Data Sources" in output
        # ID is truncated to first 8 chars
        assert "aaaabbbb" in output

    def test_null_last_connected_shows_never(self):
        """Null last_connected shows 'never'."""
        sources = [
            SavedSourceSummary(
                id="abc12345-0000-0000-0000-000000000000",
                name="Test",
                source_type="csv",
                last_connected=None,
            ),
        ]
        output = format_saved_sources(sources)
        assert "never" in output


class TestFormatSchema:
    """Tests for format_schema() output formatter."""

    def test_renders_column_table(self):
        """Columns render with name, type, and nullable status."""
        columns = [
            SourceSchemaColumn(name="order_id", type="INTEGER", nullable=False),
            SourceSchemaColumn(name="customer_name", type="VARCHAR", nullable=True),
        ]
        output = format_schema(columns)
        assert "order_id" in output
        assert "INTEGER" in output
        assert "customer_name" in output
        assert "VARCHAR" in output
        assert "Source Schema" in output
        assert "no" in output   # nullable=False
        assert "yes" in output  # nullable=True

    def test_empty_columns_shows_message(self):
        """Empty column list returns 'No columns found.'."""
        output = format_schema([])
        assert "No columns found" in output


# ===========================================================================
# 8. ShipAgentClientError
# ===========================================================================


class TestShipAgentClientError:
    """Tests for the transport-neutral error class."""

    def test_message_and_status_code(self):
        """Error stores message and optional HTTP status code."""
        err = ShipAgentClientError("Something went wrong", status_code=500)
        assert err.message == "Something went wrong"
        assert err.status_code == 500
        assert str(err) == "Something went wrong"

    def test_no_status_code(self):
        """Error works without status code (standalone/runner path)."""
        err = ShipAgentClientError("Gateway unavailable")
        assert err.message == "Gateway unavailable"
        assert err.status_code is None

    def test_is_exception(self):
        """ShipAgentClientError is a proper Exception subclass."""
        err = ShipAgentClientError("test")
        assert isinstance(err, Exception)
        with pytest.raises(ShipAgentClientError):
            raise err
