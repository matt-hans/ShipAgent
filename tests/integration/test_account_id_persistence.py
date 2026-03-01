# tests/integration/test_account_id_persistence.py
"""Integration test: activate_platform → resolve_auth_args with real DB.

Verifies the full account_id persistence path end-to-end:
1. PlatformActivationService calls auth.connect and persists account_id
2. PlatformRegistry._resolve_shopify_from_db reads account_id from DB
3. resolve_shopify_credentials receives the correct store_domain

Uses real SQLite DB and real PlatformRegistry — only the MCP session
(FakeSession) and the data upsert target (MockDataSourceClient) are faked.
"""
import pytest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base
from src.services.platform_registry import PlatformRegistry, PLATFORM_CONFIGS
from src.services.platform_activation_service import PlatformActivationService
from src.services.platform_gateway import PlatformGateway
from tests.services.fake_mcp_session import FakeSession


# --- Helpers ---

def _make_order(order_id: str) -> dict:
    """Minimal order dict for the dummy mapper."""
    return {
        "id": order_id,
        "order_number": order_id.replace("D", "100"),
        "status": "open",
        "payment_status": "paid",
        "fulfillment_status": None,
        "created_at": "2026-02-20T10:00:00Z",
        "updated_at": "2026-02-20T10:00:00Z",
        "total_price": "25.00",
        "currency": "USD",
        "customer_name": f"Customer {order_id}",
        "customer_email": f"{order_id.lower()}@test.com",
        "shipping_address": {
            "name": f"Customer {order_id}",
            "address1": f"{order_id} Main St",
            "city": "Austin",
            "state": "TX",
            "zip": "78701",
            "country_code": "US",
        },
        "line_items": [{"quantity": 1, "grams": 500, "title": "Widget"}],
        "tags": "test",
    }


class MockDataSourceClient:
    """Captures upsert_records calls without a real MCP server."""

    async def upsert_records(
        self, records: list[dict], table_name: str, pk_columns: list[str],
    ) -> dict:
        """Return synthetic counts."""
        return {"inserted": len(records), "updated": 0, "skipped": 0}


# --- Fixtures ---

@pytest.fixture
def real_registry(tmp_path):
    """Real PlatformRegistry backed by a temp SQLite file."""
    db_path = str(tmp_path / "integration.db")
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    return PlatformRegistry(factory)


@pytest.fixture
def mock_ds():
    """Mock data source client and async getter."""
    client = MockDataSourceClient()

    async def getter():
        return client

    return getter


# --- Tests ---

class TestAccountIdPersistenceEndToEnd:
    """activate_platform persists account_id → resolve_auth_args reads it back."""

    @pytest.mark.asyncio
    async def test_activate_then_resolve_uses_persisted_account_id(
        self, real_registry, mock_ds,
    ):
        """Full path: activate sets account_id in DB, resolve reads it for lookup."""
        account_domain = "my-shop.myshopify.com"
        account_label = "My Shop"

        # Build FakeSession that returns account_id from auth.connect
        session = FakeSession()
        session.program("platform.health", [{"ok": True, "contract_version": "1.0"}])
        session.program("platform.capabilities", [{
            "platform_id": "dummy",
            "contract_version": "1.0",
            "supports": ["orders.list"],
            "limits": {"rate_limit_per_second": 100, "max_concurrency": 10},
            "paging": {"default_page_size": 50, "max_page_size": 50},
        }])
        session.program("auth.connect", [{
            "ok": True,
            "account_id": account_domain,
            "account_label": account_label,
        }])
        session.program("orders.list", [{
            "items": [_make_order("D001")],
            "next_cursor": None,
            "watermark": "2026-02-28T10:00:00Z",
        }])

        gateway = PlatformGateway(
            real_registry, session_factory=lambda cfg, ref: session,
        )
        service = PlatformActivationService(
            registry=real_registry, gateway=gateway,
        )

        # Step 1: Activate — this persists account_id from auth.connect
        patch_target = "src.services.gateway_provider.get_data_gateway"
        with patch(patch_target, new=mock_ds):
            await service.activate_platform("dummy", "test", mode="initial")

        # Step 2: Verify account_id is persisted in real DB
        state = real_registry.get_state("dummy", "test")
        assert state is not None
        assert state.account_id == account_domain
        assert state.account_label == account_label

        # Step 3: Verify resolve path reads account_id
        # Dummy has no required_secret_keys, so resolve_auth_args returns
        # immediately. Instead, test the Shopify path directly since that's
        # where account_id is consumed. Create a Shopify state row with the
        # same pattern the activation service would produce.
        real_registry.update_state(
            "shopify", "store_a",
            connection_status="connected",
            account_id="store-a.myshopify.com",
            account_label="Store A",
        )

        # Patch resolve_shopify_credentials to capture the store_domain arg
        with patch(
            "src.services.platform_registry.resolve_shopify_credentials",
        ) as mock_resolve, patch(
            "src.services.platform_registry.KeyringStore",
        ) as mock_ks_cls:
            # Keyring returns nothing — forces DB fallback path
            mock_ks = mock_ks_cls.return_value
            mock_ks.get.return_value = None

            from src.services.connection_types import ShopifyLegacyCredentials
            mock_resolve.return_value = ShopifyLegacyCredentials(
                access_token="shpat_store_a",
                store_domain="store-a.myshopify.com",
            )

            args = real_registry.resolve_auth_args("shopify", "store_a")

        # The real DB row's account_id was passed through as store_domain
        mock_resolve.assert_called_once_with(store_domain="store-a.myshopify.com")
        assert args["access_token"] == "shpat_store_a"
        assert args["store_domain"] == "store-a.myshopify.com"

        await gateway.shutdown()

    @pytest.mark.asyncio
    async def test_second_profile_does_not_cross_contaminate(
        self, real_registry, mock_ds,
    ):
        """Two Shopify profiles persist independent account_ids."""
        real_registry.update_state(
            "shopify", "store_a",
            connection_status="connected",
            account_id="store-a.myshopify.com",
            account_label="Store A",
        )
        real_registry.update_state(
            "shopify", "store_b",
            connection_status="connected",
            account_id="store-b.myshopify.com",
            account_label="Store B",
        )

        # Verify each profile has its own account_id in the real DB
        state_a = real_registry.get_state("shopify", "store_a")
        state_b = real_registry.get_state("shopify", "store_b")
        assert state_a.account_id == "store-a.myshopify.com"
        assert state_b.account_id == "store-b.myshopify.com"

        # Resolve each profile and verify they get different store_domains
        with patch(
            "src.services.platform_registry.resolve_shopify_credentials",
        ) as mock_resolve, patch(
            "src.services.platform_registry.KeyringStore",
        ) as mock_ks_cls:
            mock_ks = mock_ks_cls.return_value
            mock_ks.get.return_value = None

            from src.services.connection_types import ShopifyLegacyCredentials

            # First call for store_a
            mock_resolve.return_value = ShopifyLegacyCredentials(
                access_token="shpat_a", store_domain="store-a.myshopify.com",
            )
            args_a = real_registry.resolve_auth_args("shopify", "store_a")

            # Second call for store_b
            mock_resolve.return_value = ShopifyLegacyCredentials(
                access_token="shpat_b", store_domain="store-b.myshopify.com",
            )
            args_b = real_registry.resolve_auth_args("shopify", "store_b")

        # Verify each resolve got the correct store_domain
        calls = mock_resolve.call_args_list
        assert calls[0].kwargs["store_domain"] == "store-a.myshopify.com"
        assert calls[1].kwargs["store_domain"] == "store-b.myshopify.com"
        assert args_a["access_token"] == "shpat_a"
        assert args_b["access_token"] == "shpat_b"
