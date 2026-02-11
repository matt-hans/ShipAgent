"""Tests for CommandProcessor service.

Tests the processing pipeline that converts natural language commands
into ready-to-preview jobs with JobRows and cost estimates.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base, Job, JobRow, JobStatus, RowStatus
from src.mcp.external_sources.models import ExternalOrder
from src.orchestrator.models.filter import ColumnInfo, SQLFilterResult
from src.orchestrator.models.intent import FilterCriteria, ServiceCode, ShippingIntent
from src.orchestrator.nl_engine.filter_generator import FilterGenerationError
from src.orchestrator.nl_engine.intent_parser import IntentParseError
from src.services.command_processor import (
    SHOPIFY_ORDER_SCHEMA,
    CommandProcessor,
    _order_matches_filter,
    _split_compound_clause,
    apply_filter_to_orders,
    compute_order_checksum,
)


# === Fixtures ===


@pytest.fixture
def test_engine():
    """Create an in-memory SQLite engine for testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def test_session_local(test_engine):
    """Create a session factory bound to the test engine."""
    return sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture
def test_db(test_session_local) -> Session:
    """Create a test database session."""
    session = test_session_local()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def db_session_factory(test_session_local):
    """Create a session factory that returns new sessions from shared engine."""
    def factory():
        return test_session_local()
    return factory


@pytest.fixture
def sample_order() -> ExternalOrder:
    """Create a sample order for testing."""
    return ExternalOrder(
        platform="shopify",
        order_id="123456789",
        order_number="1001",
        status="paid/unfulfilled",
        created_at="2025-01-15T10:30:00Z",
        customer_name="John Smith",
        customer_email="john@example.com",
        ship_to_name="John Smith",
        ship_to_company=None,
        ship_to_address1="123 Main St",
        ship_to_address2=None,
        ship_to_city="Los Angeles",
        ship_to_state="CA",
        ship_to_postal_code="90210",
        ship_to_country="US",
        ship_to_phone="555-1234",
        items=[{"id": "1", "title": "Widget", "quantity": 1, "price": "19.99"}],
        raw_data=None,
    )


@pytest.fixture
def sample_orders() -> list[ExternalOrder]:
    """Create multiple sample orders for testing."""
    return [
        ExternalOrder(
            platform="shopify",
            order_id="123456789",
            order_number="1001",
            status="paid/unfulfilled",
            created_at="2025-01-15T10:30:00Z",
            customer_name="John Smith",
            customer_email="john@example.com",
            ship_to_name="John Smith",
            ship_to_address1="123 Main St",
            ship_to_city="Los Angeles",
            ship_to_state="CA",
            ship_to_postal_code="90210",
            ship_to_country="US",
            items=[],
        ),
        ExternalOrder(
            platform="shopify",
            order_id="123456790",
            order_number="1002",
            status="paid/unfulfilled",
            created_at="2025-01-15T11:30:00Z",
            customer_name="Jane Doe",
            customer_email="jane@example.com",
            ship_to_name="Jane Doe",
            ship_to_address1="456 Oak Ave",
            ship_to_city="New York",
            ship_to_state="NY",
            ship_to_postal_code="10001",
            ship_to_country="US",
            items=[],
        ),
        ExternalOrder(
            platform="shopify",
            order_id="123456791",
            order_number="1003",
            status="paid/unfulfilled",
            created_at="2025-01-15T12:30:00Z",
            customer_name="Bob Johnson",
            customer_email="bob@example.com",
            ship_to_name="Bob Johnson",
            ship_to_address1="789 Pine Rd",
            ship_to_city="San Francisco",
            ship_to_state="CA",
            ship_to_postal_code="94102",
            ship_to_country="US",
            items=[],
        ),
    ]


@pytest.fixture
def pending_job(test_db: Session) -> Job:
    """Create a pending job in the test database."""
    job = Job(
        name="Test Command",
        original_command="Ship California orders using UPS Ground",
        status=JobStatus.pending.value,
    )
    test_db.add(job)
    test_db.commit()
    test_db.refresh(job)
    return job


@pytest.fixture
def mock_platform_manager(sample_orders):
    """Create a mock platform state manager."""
    manager = MagicMock()
    mock_client = AsyncMock()
    mock_client.fetch_orders = AsyncMock(return_value=sample_orders)
    manager.get_client = AsyncMock(return_value=mock_client)
    return manager


# === Tests for compute_order_checksum ===


class TestComputeOrderChecksum:
    """Tests for the compute_order_checksum function."""

    def test_checksum_is_deterministic(self, sample_order):
        """Same order produces same checksum."""
        checksum1 = compute_order_checksum(sample_order)
        checksum2 = compute_order_checksum(sample_order)
        assert checksum1 == checksum2

    def test_checksum_is_sha256_hex(self, sample_order):
        """Checksum is a 64-character hex string (SHA-256)."""
        checksum = compute_order_checksum(sample_order)
        assert len(checksum) == 64
        assert all(c in "0123456789abcdef" for c in checksum)

    def test_different_orders_different_checksums(self, sample_orders):
        """Different orders produce different checksums."""
        checksums = [compute_order_checksum(order) for order in sample_orders]
        assert len(set(checksums)) == len(checksums)


# === Tests for apply_filter_to_orders ===


class TestApplyFilterToOrders:
    """Tests for the apply_filter_to_orders function."""

    def test_empty_filter_returns_all(self, sample_orders):
        """Empty or trivial filter returns all orders."""
        filter_result = SQLFilterResult(
            where_clause="1=1",
            columns_used=[],
            original_expression="all orders",
        )
        result = apply_filter_to_orders(sample_orders, filter_result)
        assert len(result) == len(sample_orders)

    def test_state_filter_matches(self, sample_orders):
        """State filter correctly filters orders."""
        filter_result = SQLFilterResult(
            where_clause="ship_to_state = 'CA'",
            columns_used=["ship_to_state"],
            original_expression="California orders",
        )
        result = apply_filter_to_orders(sample_orders, filter_result)
        assert len(result) == 2  # John and Bob are in CA
        assert all(order.ship_to_state == "CA" for order in result)

    def test_state_filter_case_insensitive(self, sample_orders):
        """State filter is case insensitive."""
        filter_result = SQLFilterResult(
            where_clause="ship_to_state = 'ca'",
            columns_used=["ship_to_state"],
            original_expression="California orders",
        )
        result = apply_filter_to_orders(sample_orders, filter_result)
        assert len(result) == 2

    def test_status_like_filter(self, sample_orders):
        """Status LIKE filter correctly matches."""
        filter_result = SQLFilterResult(
            where_clause="status LIKE '%unfulfilled%'",
            columns_used=["status"],
            original_expression="unfulfilled orders",
        )
        result = apply_filter_to_orders(sample_orders, filter_result)
        assert len(result) == 3  # All are unfulfilled

    def test_city_filter(self, sample_orders):
        """City filter correctly matches."""
        filter_result = SQLFilterResult(
            where_clause="ship_to_city = 'Los Angeles'",
            columns_used=["ship_to_city"],
            original_expression="Los Angeles orders",
        )
        result = apply_filter_to_orders(sample_orders, filter_result)
        assert len(result) == 1
        assert result[0].ship_to_city == "Los Angeles"


# === Tests for compound filter parsing (AND/OR) ===


class TestSplitCompoundClause:
    """Tests for _split_compound_clause helper."""

    def test_single_clause_returns_single(self):
        """A simple clause with no AND/OR returns as-is."""
        op, parts = _split_compound_clause("ship_to_state = 'CA'")
        assert op == "SINGLE"
        assert parts == ["ship_to_state = 'CA'"]

    def test_or_splits_two_clauses(self):
        """OR splits into two sub-clauses."""
        op, parts = _split_compound_clause(
            "customer_name = 'Noah Bode' OR ship_to_name = 'Noah Bode'"
        )
        assert op == "OR"
        assert len(parts) == 2
        assert "customer_name = 'Noah Bode'" in parts
        assert "ship_to_name = 'Noah Bode'" in parts

    def test_and_splits_two_clauses(self):
        """AND splits into two sub-clauses."""
        op, parts = _split_compound_clause(
            "ship_to_state = 'CA' AND status LIKE '%unfulfilled%'"
        )
        assert op == "AND"
        assert len(parts) == 2

    def test_strips_outer_parens(self):
        """Outer parentheses are stripped before splitting."""
        op, parts = _split_compound_clause(
            "(customer_name = 'X' OR ship_to_name = 'X')"
        )
        assert op == "OR"
        assert len(parts) == 2


class TestCompoundFilterEvaluation:
    """Tests for AND/OR compound filter evaluation."""

    @pytest.fixture
    def order_different_names(self) -> ExternalOrder:
        """Order where buyer and recipient differ."""
        return ExternalOrder(
            platform="shopify",
            order_id="999",
            order_number="2001",
            status="paid/unfulfilled",
            created_at="2025-01-20T10:00:00Z",
            customer_name="Alice Buyer",
            customer_email="alice@example.com",
            ship_to_name="Bob Recipient",
            ship_to_address1="100 Ship St",
            ship_to_city="Buffalo",
            ship_to_state="NY",
            ship_to_postal_code="14201",
            ship_to_country="US",
            items=[],
        )

    def test_or_matches_customer_name(self, order_different_names):
        """OR filter matches when customer_name matches."""
        clause = "customer_name = 'Alice Buyer' OR ship_to_name = 'Alice Buyer'"
        assert _order_matches_filter(order_different_names, clause) is True

    def test_or_matches_ship_to_name(self, order_different_names):
        """OR filter matches when ship_to_name matches."""
        clause = "customer_name = 'Bob Recipient' OR ship_to_name = 'Bob Recipient'"
        assert _order_matches_filter(order_different_names, clause) is True

    def test_or_no_match(self, order_different_names):
        """OR filter rejects when neither side matches."""
        clause = "customer_name = 'Nobody' OR ship_to_name = 'Nobody'"
        assert _order_matches_filter(order_different_names, clause) is False

    def test_and_both_match(self, sample_orders):
        """AND filter matches when both conditions hold."""
        clause = "ship_to_state = 'CA' AND ship_to_city = 'Los Angeles'"
        # John Smith is in Los Angeles, CA
        assert _order_matches_filter(sample_orders[0], clause) is True

    def test_and_one_fails(self, sample_orders):
        """AND filter rejects when one condition fails."""
        clause = "ship_to_state = 'CA' AND ship_to_city = 'New York'"
        # John Smith is in CA but city is Los Angeles, not New York
        assert _order_matches_filter(sample_orders[0], clause) is False

    def test_customer_name_exact_match(self, sample_orders):
        """Exact customer_name filter matches."""
        clause = "customer_name = 'John Smith'"
        assert _order_matches_filter(sample_orders[0], clause) is True
        assert _order_matches_filter(sample_orders[1], clause) is False

    def test_customer_name_like_match(self, sample_orders):
        """LIKE customer_name filter matches substring."""
        clause = "customer_name LIKE '%Smith%'"
        assert _order_matches_filter(sample_orders[0], clause) is True
        assert _order_matches_filter(sample_orders[1], clause) is False

    def test_apply_or_filter_to_orders(self, sample_orders):
        """apply_filter_to_orders works with OR compound clause."""
        filter_result = SQLFilterResult(
            where_clause="customer_name = 'John Smith' OR customer_name = 'Jane Doe'",
            columns_used=["customer_name"],
            original_expression="orders for John Smith or Jane Doe",
        )
        result = apply_filter_to_orders(sample_orders, filter_result)
        assert len(result) == 2
        names = {o.customer_name for o in result}
        assert names == {"John Smith", "Jane Doe"}


# === Tests for numeric filter evaluation ===


class TestNumericFilterEvaluation:
    """Tests for total_price numeric comparison in _order_matches_filter."""

    @pytest.fixture
    def order_with_price(self) -> ExternalOrder:
        """Order with total_price set."""
        return ExternalOrder(
            platform="shopify",
            order_id="price-001",
            order_number="3001",
            status="paid/unfulfilled",
            created_at="2025-01-20T10:00:00Z",
            customer_name="Alice Price",
            customer_email="alice@example.com",
            ship_to_name="Alice Price",
            ship_to_address1="100 Price St",
            ship_to_city="Denver",
            ship_to_state="CO",
            ship_to_postal_code="80201",
            ship_to_country="US",
            total_price="149.99",
            items=[],
        )

    def test_total_price_greater_than_match(self, order_with_price):
        """total_price > 100 matches order with $149.99."""
        assert _order_matches_filter(order_with_price, "total_price > 100") is True

    def test_total_price_greater_than_no_match(self, order_with_price):
        """total_price > 200 does not match order with $149.99."""
        assert _order_matches_filter(order_with_price, "total_price > 200") is False

    def test_total_price_less_than(self, order_with_price):
        """total_price < 200 matches order with $149.99."""
        assert _order_matches_filter(order_with_price, "total_price < 200") is True

    def test_total_price_greater_equal(self, order_with_price):
        """total_price >= 149.99 matches exactly."""
        assert _order_matches_filter(order_with_price, "total_price >= 149.99") is True

    def test_total_price_less_equal(self, order_with_price):
        """total_price <= 149.99 matches exactly."""
        assert _order_matches_filter(order_with_price, "total_price <= 149.99") is True

    def test_total_price_equal(self, order_with_price):
        """total_price = 149.99 matches exactly."""
        assert _order_matches_filter(order_with_price, "total_price = 149.99") is True

    def test_total_price_not_equal(self, order_with_price):
        """total_price != 100 matches when price is different."""
        assert _order_matches_filter(order_with_price, "total_price != 100") is True

    def test_total_price_none_treated_as_zero(self):
        """Order with no total_price treats it as 0."""
        order = ExternalOrder(
            platform="shopify",
            order_id="no-price",
            order_number="3002",
            status="paid/unfulfilled",
            created_at="2025-01-20T10:00:00Z",
            customer_name="No Price",
            ship_to_name="No Price",
            ship_to_address1="200 Zero St",
            ship_to_city="Portland",
            ship_to_state="OR",
            ship_to_postal_code="97201",
            ship_to_country="US",
            total_price=None,
            items=[],
        )
        assert _order_matches_filter(order, "total_price > 100") is False
        assert _order_matches_filter(order, "total_price >= 0") is True

    def test_apply_filter_with_price(self):
        """apply_filter_to_orders correctly filters by total_price."""
        orders = [
            ExternalOrder(
                platform="shopify",
                order_id=f"ord-{i}",
                order_number=str(i),
                status="paid/unfulfilled",
                created_at="2025-01-20T10:00:00Z",
                customer_name=f"Customer {i}",
                ship_to_name=f"Customer {i}",
                ship_to_address1=f"{i} Main St",
                ship_to_city="Denver",
                ship_to_state="CO",
                ship_to_postal_code="80201",
                ship_to_country="US",
                total_price=price,
                items=[],
            )
            for i, price in enumerate(["49.99", "150.00", "250.00"], start=1)
        ]
        filter_result = SQLFilterResult(
            where_clause="total_price > 100",
            columns_used=["total_price"],
            original_expression="orders over $100",
        )
        result = apply_filter_to_orders(orders, filter_result)
        assert len(result) == 2
        assert all(float(o.total_price) > 100 for o in result)


# === Tests for SHOPIFY_ORDER_SCHEMA ===


class TestShopifyOrderSchema:
    """Tests for the schema definition."""

    def test_schema_has_required_columns(self):
        """Schema includes all required columns for filter generation."""
        column_names = [col.name for col in SHOPIFY_ORDER_SCHEMA]
        assert "ship_to_state" in column_names
        assert "ship_to_city" in column_names
        assert "status" in column_names
        assert "created_at" in column_names
        assert "order_id" in column_names

    def test_schema_has_sample_values(self):
        """Schema columns have sample values for LLM context."""
        state_col = next(c for c in SHOPIFY_ORDER_SCHEMA if c.name == "ship_to_state")
        assert len(state_col.sample_values) > 0
        assert "CA" in state_col.sample_values

    def test_schema_has_correct_types(self):
        """Schema columns have appropriate types."""
        created_at = next(c for c in SHOPIFY_ORDER_SCHEMA if c.name == "created_at")
        assert created_at.type == "datetime"

        state = next(c for c in SHOPIFY_ORDER_SCHEMA if c.name == "ship_to_state")
        assert state.type == "string"

    def test_schema_has_total_price(self):
        """Schema includes total_price as a numeric column."""
        column_names = [col.name for col in SHOPIFY_ORDER_SCHEMA]
        assert "total_price" in column_names
        price_col = next(c for c in SHOPIFY_ORDER_SCHEMA if c.name == "total_price")
        assert price_col.type == "numeric"


# === Tests for CommandProcessor ===


class TestCommandProcessorInit:
    """Tests for CommandProcessor initialization."""

    def test_init_with_factory(self, db_session_factory):
        """Can initialize with session factory."""
        processor = CommandProcessor(db_session_factory=db_session_factory)
        assert processor._db_session_factory is db_session_factory

    def test_init_with_platform_manager(self, db_session_factory, mock_platform_manager):
        """Can initialize with custom platform manager."""
        processor = CommandProcessor(
            db_session_factory=db_session_factory,
            platform_state_manager=mock_platform_manager,
        )
        assert processor._platform_state_manager is mock_platform_manager


class TestCommandProcessorProcess:
    """Tests for CommandProcessor.process method."""

    def _get_job(self, db_session_factory, job_id: str) -> Job:
        """Helper to get job from a fresh session."""
        session = db_session_factory()
        try:
            return session.query(Job).filter(Job.id == job_id).first()
        finally:
            session.close()

    def _get_job_rows(self, db_session_factory, job_id: str) -> list[JobRow]:
        """Helper to get job rows from a fresh session."""
        session = db_session_factory()
        try:
            return session.query(JobRow).filter(JobRow.job_id == job_id).all()
        finally:
            session.close()

    @pytest.mark.asyncio
    async def test_process_sets_error_on_intent_parse_failure(
        self,
        db_session_factory,
        pending_job,
    ):
        """Sets error when intent parsing fails."""
        job_id = pending_job.id
        processor = CommandProcessor(db_session_factory=db_session_factory)

        with patch(
            "src.services.command_processor.parse_intent",
            side_effect=IntentParseError(
                message="Cannot parse command",
                original_command="gibberish",
                suggestions=["Try: Ship orders via Ground"],
            ),
        ):
            await processor.process(job_id, "gibberish")

        job = self._get_job(db_session_factory, job_id)
        assert job.error_code == "E-4002"
        assert "Cannot parse command" in job.error_message
        assert "Try:" in job.error_message

    @pytest.mark.asyncio
    async def test_process_sets_error_when_shopify_not_connected(
        self,
        db_session_factory,
        pending_job,
    ):
        """Sets error when Shopify is not connected."""
        job_id = pending_job.id
        mock_manager = MagicMock()
        mock_manager.get_client = AsyncMock(return_value=None)

        processor = CommandProcessor(
            db_session_factory=db_session_factory,
            platform_state_manager=mock_manager,
        )

        intent = ShippingIntent(action="ship", service_code=ServiceCode.GROUND)

        with patch("src.services.command_processor.parse_intent", return_value=intent):
            await processor.process(job_id, "Ship orders")

        job = self._get_job(db_session_factory, job_id)
        assert job.error_code == "E-5002"
        assert "Shopify not connected" in job.error_message

    @pytest.mark.asyncio
    async def test_process_sets_error_when_no_orders(
        self,
        db_session_factory,
        pending_job,
    ):
        """Sets error when no orders are fetched."""
        job_id = pending_job.id
        mock_manager = MagicMock()
        mock_client = AsyncMock()
        mock_client.fetch_orders = AsyncMock(return_value=[])
        mock_manager.get_client = AsyncMock(return_value=mock_client)

        processor = CommandProcessor(
            db_session_factory=db_session_factory,
            platform_state_manager=mock_manager,
        )

        intent = ShippingIntent(action="ship", service_code=ServiceCode.GROUND)

        with patch("src.services.command_processor.parse_intent", return_value=intent):
            await processor.process(job_id, "Ship orders")

        job = self._get_job(db_session_factory, job_id)
        assert job.error_code == "E-1001"
        assert "No unfulfilled orders" in job.error_message

    @pytest.mark.asyncio
    async def test_process_creates_job_rows(
        self,
        db_session_factory,
        pending_job,
        sample_orders,
    ):
        """Creates JobRows for filtered orders with real UPS rate quotes."""
        job_id = pending_job.id
        mock_manager = MagicMock()
        mock_client = AsyncMock()
        mock_client.fetch_orders = AsyncMock(return_value=sample_orders)
        mock_manager.get_client = AsyncMock(return_value=mock_client)

        processor = CommandProcessor(
            db_session_factory=db_session_factory,
            platform_state_manager=mock_manager,
        )

        # Intent without filter - should get all orders
        intent = ShippingIntent(action="ship", service_code=ServiceCode.GROUND)

        # Mock BatchEngine.preview to return realistic costs
        mock_preview_result = {
            "job_id": job_id,
            "total_rows": 3,
            "preview_rows": [
                {"row_number": 1, "recipient_name": "John Smith",
                 "city_state": "Los Angeles, CA", "estimated_cost_cents": 1250},
                {"row_number": 2, "recipient_name": "Jane Doe",
                 "city_state": "New York, NY", "estimated_cost_cents": 1580},
                {"row_number": 3, "recipient_name": "Bob Johnson",
                 "city_state": "San Francisco, CA", "estimated_cost_cents": 1100},
            ],
            "additional_rows": 0,
            "total_estimated_cost_cents": 3930,
        }

        with patch("src.services.command_processor.parse_intent", return_value=intent):
            with patch(
                "src.services.command_processor.BatchEngine.preview",
                new_callable=AsyncMock,
                return_value=mock_preview_result,
            ):
                with patch("src.services.command_processor.UPSService"):
                    await processor.process(job_id, "Ship all orders")

        # Check job was updated
        job = self._get_job(db_session_factory, job_id)
        assert job.total_rows == 3
        assert job.error_code is None

        # Check rows were created with real costs
        rows = self._get_job_rows(db_session_factory, job_id)
        assert len(rows) == 3
        assert all(row.status == RowStatus.pending.value for row in rows)
        assert all(row.cost_cents > 0 for row in rows)
        assert all(row.row_checksum is not None for row in rows)

        # Verify specific costs from the mock preview
        rows_by_num = {r.row_number: r for r in rows}
        assert rows_by_num[1].cost_cents == 1250
        assert rows_by_num[2].cost_cents == 1580
        assert rows_by_num[3].cost_cents == 1100

    @pytest.mark.asyncio
    async def test_process_applies_state_filter(
        self,
        db_session_factory,
        pending_job,
        sample_orders,
    ):
        """Applies filter and only creates rows for matching orders."""
        job_id = pending_job.id
        mock_manager = MagicMock()
        mock_client = AsyncMock()
        mock_client.fetch_orders = AsyncMock(return_value=sample_orders)
        mock_manager.get_client = AsyncMock(return_value=mock_client)

        processor = CommandProcessor(
            db_session_factory=db_session_factory,
            platform_state_manager=mock_manager,
        )

        # Intent with California filter
        intent = ShippingIntent(
            action="ship",
            service_code=ServiceCode.GROUND,
            filter_criteria=FilterCriteria(
                raw_expression="California orders",
                filter_type="state",
            ),
        )

        filter_result = SQLFilterResult(
            where_clause="ship_to_state = 'CA'",
            columns_used=["ship_to_state"],
            original_expression="California orders",
        )

        mock_preview_result = {
            "job_id": job_id,
            "total_rows": 2,
            "preview_rows": [
                {"row_number": 1, "recipient_name": "John Smith",
                 "city_state": "Los Angeles, CA", "estimated_cost_cents": 1250},
                {"row_number": 2, "recipient_name": "Bob Johnson",
                 "city_state": "San Francisco, CA", "estimated_cost_cents": 1100},
            ],
            "additional_rows": 0,
            "total_estimated_cost_cents": 2350,
        }

        with patch("src.services.command_processor.parse_intent", return_value=intent):
            with patch(
                "src.services.command_processor.generate_filter",
                return_value=filter_result,
            ):
                with patch(
                    "src.services.command_processor.BatchEngine.preview",
                    new_callable=AsyncMock,
                    return_value=mock_preview_result,
                ):
                    with patch("src.services.command_processor.UPSService"):
                        await processor.process(job_id, "Ship California orders")

        # Should only have 2 rows (CA orders)
        job = self._get_job(db_session_factory, job_id)
        assert job.total_rows == 2
        rows = self._get_job_rows(db_session_factory, job_id)
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_process_handles_clarification_needed(
        self,
        db_session_factory,
        pending_job,
        sample_orders,
    ):
        """Sets error when filter needs clarification."""
        job_id = pending_job.id
        mock_manager = MagicMock()
        mock_client = AsyncMock()
        mock_client.fetch_orders = AsyncMock(return_value=sample_orders)
        mock_manager.get_client = AsyncMock(return_value=mock_client)

        processor = CommandProcessor(
            db_session_factory=db_session_factory,
            platform_state_manager=mock_manager,
        )

        intent = ShippingIntent(
            action="ship",
            filter_criteria=FilterCriteria(
                raw_expression="today's orders",
                filter_type="date",
            ),
        )

        filter_result = SQLFilterResult(
            where_clause="created_at >= '2025-01-15'",
            columns_used=["created_at"],
            date_column="created_at",
            needs_clarification=True,
            clarification_questions=["Which date column should be used?"],
            original_expression="today's orders",
        )

        with patch("src.services.command_processor.parse_intent", return_value=intent):
            with patch(
                "src.services.command_processor.generate_filter",
                return_value=filter_result,
            ):
                await processor.process(job_id, "Ship today's orders")

        job = self._get_job(db_session_factory, job_id)
        assert job.error_code == "E-4003"
        assert "ambiguous" in job.error_message.lower()
        assert "Which date column" in job.error_message

    @pytest.mark.asyncio
    async def test_process_handles_filter_generation_error(
        self,
        db_session_factory,
        pending_job,
    ):
        """Sets error when filter generation fails."""
        job_id = pending_job.id
        mock_manager = MagicMock()
        mock_manager.get_client = AsyncMock(return_value=AsyncMock())

        processor = CommandProcessor(
            db_session_factory=db_session_factory,
            platform_state_manager=mock_manager,
        )

        intent = ShippingIntent(
            action="ship",
            filter_criteria=FilterCriteria(
                raw_expression="invalid column filter",
                filter_type="none",
            ),
        )

        with patch("src.services.command_processor.parse_intent", return_value=intent):
            with patch(
                "src.services.command_processor.generate_filter",
                side_effect=FilterGenerationError(
                    message="Column 'xyz' not found",
                    original_expression="xyz = 1",
                    available_columns=["ship_to_state"],
                ),
            ):
                await processor.process(job_id, "Filter by xyz")

        job = self._get_job(db_session_factory, job_id)
        assert job.error_code == "E-4004"
        assert "Column" in job.error_message


class TestCommandProcessorUPSRating:
    """Tests for real UPS rate integration via BatchEngine.preview()."""

    def _get_job_rows(self, db_session_factory, job_id: str) -> list[JobRow]:
        """Helper to get job rows from a fresh session."""
        session = db_session_factory()
        try:
            return session.query(JobRow).filter(JobRow.job_id == job_id).all()
        finally:
            session.close()

    @pytest.mark.asyncio
    async def test_batch_engine_preview_called_with_correct_args(
        self,
        db_session_factory,
        pending_job,
        sample_orders,
    ):
        """BatchEngine.preview() is called with correct job_id and service_code."""
        job_id = pending_job.id
        mock_manager = MagicMock()
        mock_client = AsyncMock()
        mock_client.fetch_orders = AsyncMock(return_value=sample_orders)
        mock_manager.get_client = AsyncMock(return_value=mock_client)

        processor = CommandProcessor(
            db_session_factory=db_session_factory,
            platform_state_manager=mock_manager,
        )

        intent = ShippingIntent(action="ship", service_code=ServiceCode.NEXT_DAY_AIR)

        mock_preview = AsyncMock(return_value={
            "job_id": job_id,
            "total_rows": 3,
            "preview_rows": [
                {"row_number": 1, "recipient_name": "John Smith",
                 "city_state": "Los Angeles, CA", "estimated_cost_cents": 8500},
                {"row_number": 2, "recipient_name": "Jane Doe",
                 "city_state": "New York, NY", "estimated_cost_cents": 9200},
                {"row_number": 3, "recipient_name": "Bob Johnson",
                 "city_state": "San Francisco, CA", "estimated_cost_cents": 8100},
            ],
            "additional_rows": 0,
            "total_estimated_cost_cents": 25800,
        })

        with patch("src.services.command_processor.parse_intent", return_value=intent):
            with patch(
                "src.services.command_processor.BatchEngine.preview",
                mock_preview,
            ):
                with patch("src.services.command_processor.UPSService"):
                    await processor.process(job_id, "Ship all orders overnight")

        # Verify preview was called with correct service code
        mock_preview.assert_called_once()
        call_args = mock_preview.call_args
        assert call_args[0][0] == job_id  # job_id
        assert len(call_args[0][1]) == 3  # 3 rows
        assert call_args[0][3] == "01"  # Next Day Air service code

    @pytest.mark.asyncio
    async def test_ups_rating_failure_leaves_zero_costs(
        self,
        db_session_factory,
        pending_job,
        sample_orders,
    ):
        """If UPS rating fails entirely, rows keep cost_cents=0."""
        job_id = pending_job.id
        mock_manager = MagicMock()
        mock_client = AsyncMock()
        mock_client.fetch_orders = AsyncMock(return_value=sample_orders)
        mock_manager.get_client = AsyncMock(return_value=mock_client)

        processor = CommandProcessor(
            db_session_factory=db_session_factory,
            platform_state_manager=mock_manager,
        )

        intent = ShippingIntent(action="ship", service_code=ServiceCode.GROUND)

        with patch("src.services.command_processor.parse_intent", return_value=intent):
            with patch(
                "src.services.command_processor.UPSService",
                side_effect=Exception("UPS API credentials missing"),
            ):
                await processor.process(job_id, "Ship all orders")

        # Rows should still be created, but with cost_cents=0
        rows = self._get_job_rows(db_session_factory, job_id)
        assert len(rows) == 3
        assert all(row.cost_cents == 0 for row in rows)

    @pytest.mark.asyncio
    async def test_preview_costs_propagate_to_rows(
        self,
        db_session_factory,
        pending_job,
        sample_orders,
    ):
        """Preview result costs are correctly propagated to JobRow.cost_cents."""
        job_id = pending_job.id
        mock_manager = MagicMock()
        mock_client = AsyncMock()
        mock_client.fetch_orders = AsyncMock(return_value=sample_orders)
        mock_manager.get_client = AsyncMock(return_value=mock_client)

        processor = CommandProcessor(
            db_session_factory=db_session_factory,
            platform_state_manager=mock_manager,
        )

        intent = ShippingIntent(action="ship", service_code=ServiceCode.GROUND)

        mock_preview_result = {
            "job_id": job_id,
            "total_rows": 3,
            "preview_rows": [
                {"row_number": 1, "recipient_name": "John Smith",
                 "city_state": "Los Angeles, CA", "estimated_cost_cents": 1199},
                {"row_number": 2, "recipient_name": "Jane Doe",
                 "city_state": "New York, NY", "estimated_cost_cents": 1499},
                {"row_number": 3, "recipient_name": "Bob Johnson",
                 "city_state": "San Francisco, CA", "estimated_cost_cents": 1099},
            ],
            "additional_rows": 0,
            "total_estimated_cost_cents": 3797,
        }

        with patch("src.services.command_processor.parse_intent", return_value=intent):
            with patch(
                "src.services.command_processor.BatchEngine.preview",
                new_callable=AsyncMock,
                return_value=mock_preview_result,
            ):
                with patch("src.services.command_processor.UPSService"):
                    await processor.process(job_id, "Ship all orders")

        rows = self._get_job_rows(db_session_factory, job_id)
        rows_by_num = {r.row_number: r for r in rows}
        assert rows_by_num[1].cost_cents == 1199
        assert rows_by_num[2].cost_cents == 1499
        assert rows_by_num[3].cost_cents == 1099


class TestCommandProcessorJobNotFound:
    """Tests for edge cases with missing jobs."""

    @pytest.mark.asyncio
    async def test_process_handles_missing_job(self, db_session_factory, test_db):
        """Gracefully handles job not found."""
        processor = CommandProcessor(db_session_factory=db_session_factory)
        # Should not raise, just log error
        await processor.process("nonexistent-job-id", "Ship orders")
        # No exception means success


# === Tests for new field evaluation (6 HIGH priority fields) ===


class TestNewFieldEvaluation:
    """Tests for the 6 new filterable fields."""

    @pytest.fixture
    def rich_order(self) -> ExternalOrder:
        """Order with all new fields populated."""
        return ExternalOrder(
            platform="shopify",
            order_id="rich-001",
            order_number="5001",
            status="paid/unfulfilled",
            created_at="2025-01-20T10:00:00Z",
            customer_name="Rich Customer",
            ship_to_name="Rich Customer",
            ship_to_address1="500 Rich Ave",
            ship_to_city="Seattle",
            ship_to_state="WA",
            ship_to_postal_code="98101",
            ship_to_country="US",
            total_price="249.99",
            financial_status="paid",
            fulfillment_status="unfulfilled",
            tags="VIP, wholesale, priority",
            total_weight_grams=2500.0,
            shipping_method="Standard Shipping",
            item_count=5,
            items=[],
        )

    # financial_status tests
    def test_financial_status_exact_match(self, rich_order):
        """financial_status = 'paid' matches."""
        assert _order_matches_filter(rich_order, "financial_status = 'paid'") is True
        assert _order_matches_filter(rich_order, "financial_status = 'refunded'") is False

    def test_financial_status_like_match(self, rich_order):
        """financial_status LIKE '%pai%' matches."""
        assert _order_matches_filter(rich_order, "financial_status LIKE '%pai%'") is True
        assert _order_matches_filter(rich_order, "financial_status LIKE '%refund%'") is False

    # fulfillment_status tests
    def test_fulfillment_status_exact_match(self, rich_order):
        """fulfillment_status = 'unfulfilled' matches."""
        assert _order_matches_filter(rich_order, "fulfillment_status = 'unfulfilled'") is True
        assert _order_matches_filter(rich_order, "fulfillment_status = 'fulfilled'") is False

    # tags tests
    def test_tags_like_match(self, rich_order):
        """tags LIKE '%VIP%' matches comma-separated tags."""
        assert _order_matches_filter(rich_order, "tags LIKE '%VIP%'") is True
        assert _order_matches_filter(rich_order, "tags LIKE '%wholesale%'") is True
        assert _order_matches_filter(rich_order, "tags LIKE '%nonexistent%'") is False

    def test_tags_is_null(self):
        """tags IS NULL matches when tags is None."""
        order = ExternalOrder(
            platform="shopify",
            order_id="no-tags",
            order_number="5002",
            status="paid/unfulfilled",
            created_at="2025-01-20T10:00:00Z",
            customer_name="No Tags",
            ship_to_name="No Tags",
            ship_to_address1="100 Bare St",
            ship_to_city="Portland",
            ship_to_state="OR",
            ship_to_postal_code="97201",
            ship_to_country="US",
            tags=None,
            items=[],
        )
        assert _order_matches_filter(order, "tags IS NULL") is True
        assert _order_matches_filter(order, "tags IS NOT NULL") is False

    # total_weight_grams tests
    def test_weight_greater_than(self, rich_order):
        """total_weight_grams > 2000 matches order with 2500g."""
        assert _order_matches_filter(rich_order, "total_weight_grams > 2000") is True
        assert _order_matches_filter(rich_order, "total_weight_grams > 3000") is False

    def test_weight_less_than(self, rich_order):
        """total_weight_grams < 3000 matches order with 2500g."""
        assert _order_matches_filter(rich_order, "total_weight_grams < 3000") is True

    def test_weight_equal(self, rich_order):
        """total_weight_grams = 2500 matches exact weight."""
        assert _order_matches_filter(rich_order, "total_weight_grams = 2500") is True

    # shipping_method tests
    def test_shipping_method_exact_match(self, rich_order):
        """shipping_method = 'Standard Shipping' matches."""
        assert _order_matches_filter(rich_order, "shipping_method = 'Standard Shipping'") is True

    def test_shipping_method_like_match(self, rich_order):
        """shipping_method LIKE '%Standard%' matches substring."""
        assert _order_matches_filter(rich_order, "shipping_method LIKE '%Standard%'") is True
        assert _order_matches_filter(rich_order, "shipping_method LIKE '%Express%'") is False

    # item_count tests
    def test_item_count_comparison(self, rich_order):
        """item_count comparisons work correctly."""
        assert _order_matches_filter(rich_order, "item_count > 3") is True
        assert _order_matches_filter(rich_order, "item_count > 10") is False
        assert _order_matches_filter(rich_order, "item_count = 5") is True
        assert _order_matches_filter(rich_order, "item_count <= 5") is True
        assert _order_matches_filter(rich_order, "item_count < 5") is False


# === Regression tests for existing filter patterns ===


class TestEvaluatorRegression:
    """Regression tests ensuring all existing filter patterns still work after refactor."""

    @pytest.fixture
    def full_order(self) -> ExternalOrder:
        """Order with all fields populated for comprehensive regression testing."""
        return ExternalOrder(
            platform="shopify",
            order_id="reg-001",
            order_number="9001",
            status="paid/unfulfilled",
            created_at="2025-01-15T10:30:00Z",
            customer_name="John Smith",
            customer_email="john@example.com",
            ship_to_name="Jane Receiver",
            ship_to_company="Acme Corp",
            ship_to_address1="123 Main St",
            ship_to_address2="Suite 200",
            ship_to_city="Los Angeles",
            ship_to_state="CA",
            ship_to_postal_code="90210",
            ship_to_country="US",
            ship_to_phone="555-123-4567",
            total_price="149.99",
            financial_status="paid",
            fulfillment_status="unfulfilled",
            items=[],
        )

    # State filter
    def test_state_exact_match(self, full_order):
        """ship_to_state = 'CA' matches."""
        assert _order_matches_filter(full_order, "ship_to_state = 'CA'") is True
        assert _order_matches_filter(full_order, "ship_to_state = 'NY'") is False

    def test_state_case_insensitive(self, full_order):
        """ship_to_state = 'ca' matches case insensitively."""
        assert _order_matches_filter(full_order, "ship_to_state = 'ca'") is True

    # City filter
    def test_city_exact_match(self, full_order):
        """ship_to_city = 'Los Angeles' matches."""
        assert _order_matches_filter(full_order, "ship_to_city = 'Los Angeles'") is True
        assert _order_matches_filter(full_order, "ship_to_city = 'New York'") is False

    # Status LIKE
    def test_status_like_unfulfilled(self, full_order):
        """status LIKE '%unfulfilled%' matches composite status."""
        assert _order_matches_filter(full_order, "status LIKE '%unfulfilled%'") is True

    def test_status_like_paid(self, full_order):
        """status LIKE '%paid%' matches composite status."""
        assert _order_matches_filter(full_order, "status LIKE '%paid%'") is True

    # Status exact
    def test_status_exact_match(self, full_order):
        """status = 'paid/unfulfilled' matches."""
        assert _order_matches_filter(full_order, "status = 'paid/unfulfilled'") is True

    # Customer name
    def test_customer_name_exact(self, full_order):
        """customer_name = 'John Smith' matches."""
        assert _order_matches_filter(full_order, "customer_name = 'John Smith'") is True
        assert _order_matches_filter(full_order, "customer_name = 'Nobody'") is False

    def test_customer_name_like(self, full_order):
        """customer_name LIKE '%Smith%' matches substring."""
        assert _order_matches_filter(full_order, "customer_name LIKE '%Smith%'") is True

    # Ship-to name
    def test_ship_to_name_exact(self, full_order):
        """ship_to_name = 'Jane Receiver' matches."""
        assert _order_matches_filter(full_order, "ship_to_name = 'Jane Receiver'") is True

    def test_ship_to_name_like(self, full_order):
        """ship_to_name LIKE '%Receiver%' matches substring."""
        assert _order_matches_filter(full_order, "ship_to_name LIKE '%Receiver%'") is True

    # Company
    def test_company_exact(self, full_order):
        """ship_to_company = 'Acme Corp' matches."""
        assert _order_matches_filter(full_order, "ship_to_company = 'Acme Corp'") is True

    def test_company_like(self, full_order):
        """ship_to_company LIKE '%Acme%' matches."""
        assert _order_matches_filter(full_order, "ship_to_company LIKE '%Acme%'") is True

    # Email
    def test_email_exact(self, full_order):
        """customer_email = 'john@example.com' matches."""
        assert _order_matches_filter(full_order, "customer_email = 'john@example.com'") is True

    def test_email_like(self, full_order):
        """customer_email LIKE '%example.com%' matches substring."""
        assert _order_matches_filter(full_order, "customer_email LIKE '%example.com%'") is True

    # Postal code
    def test_postal_code_exact(self, full_order):
        """ship_to_postal_code = '90210' matches."""
        assert _order_matches_filter(full_order, "ship_to_postal_code = '90210'") is True
        assert _order_matches_filter(full_order, "ship_to_postal_code = '10001'") is False

    # Country
    def test_country_exact(self, full_order):
        """ship_to_country = 'US' matches."""
        assert _order_matches_filter(full_order, "ship_to_country = 'US'") is True
        assert _order_matches_filter(full_order, "ship_to_country = 'CA'") is False

    # Phone
    def test_phone_exact_with_normalization(self, full_order):
        """Phone numbers are normalized (digits-only comparison)."""
        assert _order_matches_filter(full_order, "ship_to_phone = '555-123-4567'") is True
        assert _order_matches_filter(full_order, "ship_to_phone = '5551234567'") is True

    def test_phone_like(self, full_order):
        """ship_to_phone LIKE '%1234%' matches substring."""
        assert _order_matches_filter(full_order, "ship_to_phone LIKE '%1234%'") is True

    # Total price numeric
    def test_total_price_greater_than(self, full_order):
        """total_price > 100 matches."""
        assert _order_matches_filter(full_order, "total_price > 100") is True
        assert _order_matches_filter(full_order, "total_price > 200") is False

    def test_total_price_less_than(self, full_order):
        """total_price < 200 matches."""
        assert _order_matches_filter(full_order, "total_price < 200") is True

    def test_total_price_equal(self, full_order):
        """total_price = 149.99 matches exactly."""
        assert _order_matches_filter(full_order, "total_price = 149.99") is True

    # Created at date
    def test_created_at_greater_equal(self, full_order):
        """created_at >= '2025-01-15' matches."""
        assert _order_matches_filter(full_order, "created_at >= '2025-01-15'") is True
        assert _order_matches_filter(full_order, "created_at >= '2025-01-16'") is False

    def test_created_at_less_than(self, full_order):
        """created_at < '2025-01-16' matches."""
        assert _order_matches_filter(full_order, "created_at < '2025-01-16'") is True

    # Order ID / number
    def test_order_id_exact(self, full_order):
        """order_id = 'reg-001' matches."""
        assert _order_matches_filter(full_order, "order_id = 'reg-001'") is True

    def test_order_number_exact(self, full_order):
        """order_number = '9001' matches."""
        assert _order_matches_filter(full_order, "order_number = '9001'") is True

    # Address
    def test_address1_exact(self, full_order):
        """ship_to_address1 = '123 Main St' matches."""
        assert _order_matches_filter(full_order, "ship_to_address1 = '123 Main St'") is True

    def test_address1_like(self, full_order):
        """ship_to_address1 LIKE '%Main%' matches."""
        assert _order_matches_filter(full_order, "ship_to_address1 LIKE '%Main%'") is True

    def test_address2_exact(self, full_order):
        """ship_to_address2 = 'Suite 200' matches."""
        assert _order_matches_filter(full_order, "ship_to_address2 = 'Suite 200'") is True

    def test_address2_is_null(self):
        """ship_to_address2 IS NULL matches when address2 is None."""
        order = ExternalOrder(
            platform="shopify",
            order_id="no-addr2",
            order_number="9002",
            status="paid/unfulfilled",
            created_at="2025-01-15T10:30:00Z",
            customer_name="No Addr2",
            ship_to_name="No Addr2",
            ship_to_address1="100 Bare St",
            ship_to_city="Portland",
            ship_to_state="OR",
            ship_to_postal_code="97201",
            ship_to_country="US",
            ship_to_address2=None,
            items=[],
        )
        assert _order_matches_filter(order, "ship_to_address2 IS NULL") is True
        assert _order_matches_filter(order, "ship_to_address2 IS NOT NULL") is False

    # Compound AND/OR
    def test_and_compound(self, full_order):
        """AND compound clause both conditions true."""
        clause = "ship_to_state = 'CA' AND ship_to_city = 'Los Angeles'"
        assert _order_matches_filter(full_order, clause) is True

    def test_and_compound_one_fails(self, full_order):
        """AND compound clause one condition false."""
        clause = "ship_to_state = 'CA' AND ship_to_city = 'New York'"
        assert _order_matches_filter(full_order, clause) is False

    def test_or_compound(self, full_order):
        """OR compound clause one condition true."""
        clause = "customer_name = 'John Smith' OR ship_to_name = 'John Smith'"
        assert _order_matches_filter(full_order, clause) is True

    def test_or_compound_no_match(self, full_order):
        """OR compound clause neither condition true."""
        clause = "customer_name = 'Nobody' OR ship_to_name = 'Nobody'"
        assert _order_matches_filter(full_order, clause) is False


class TestSchemaNewFields:
    """Verify the 6 new fields are present in the schema."""

    def test_schema_has_new_fields(self):
        """Schema includes all 6 new filterable fields."""
        column_names = [col.name for col in SHOPIFY_ORDER_SCHEMA]
        for field in [
            "financial_status",
            "fulfillment_status",
            "tags",
            "total_weight_grams",
            "shipping_method",
            "item_count",
        ]:
            assert field in column_names, f"Missing schema column: {field}"

    def test_schema_field_types(self):
        """New fields have correct types."""
        type_map = {col.name: col.type for col in SHOPIFY_ORDER_SCHEMA}
        assert type_map["financial_status"] == "string"
        assert type_map["fulfillment_status"] == "string"
        assert type_map["tags"] == "string"
        assert type_map["total_weight_grams"] == "numeric"
        assert type_map["shipping_method"] == "string"
        assert type_map["item_count"] == "integer"
