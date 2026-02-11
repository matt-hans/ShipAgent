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
        """Creates JobRows for filtered orders."""
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

        with patch("src.services.command_processor.parse_intent", return_value=intent):
            await processor.process(job_id, "Ship all orders")

        # Check job was updated
        job = self._get_job(db_session_factory, job_id)
        assert job.total_rows == 3
        assert job.error_code is None

        # Check rows were created
        rows = self._get_job_rows(db_session_factory, job_id)
        assert len(rows) == 3
        assert all(row.status == RowStatus.pending.value for row in rows)
        assert all(row.cost_cents is not None for row in rows)
        assert all(row.row_checksum is not None for row in rows)

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

        with patch("src.services.command_processor.parse_intent", return_value=intent):
            with patch(
                "src.services.command_processor.generate_filter",
                return_value=filter_result,
            ):
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


class TestCommandProcessorCostEstimation:
    """Tests for shipping cost estimation."""

    def test_ground_service_base_cost(self, db_session_factory, sample_order):
        """Ground service has expected base cost."""
        processor = CommandProcessor(db_session_factory=db_session_factory)
        cost = processor._estimate_shipping_cost(sample_order, "03")
        # CA is west coast, so 1.0 multiplier: 899 * 1.0 = 899
        assert cost == 899

    def test_next_day_air_higher_cost(self, db_session_factory, sample_order):
        """Next Day Air costs more than Ground."""
        processor = CommandProcessor(db_session_factory=db_session_factory)
        ground_cost = processor._estimate_shipping_cost(sample_order, "03")
        next_day_cost = processor._estimate_shipping_cost(sample_order, "01")
        assert next_day_cost > ground_cost

    def test_east_coast_higher_cost(self, db_session_factory):
        """East coast shipping costs more (assuming west coast origin)."""
        processor = CommandProcessor(db_session_factory=db_session_factory)

        ca_order = ExternalOrder(
            platform="shopify",
            order_id="1",
            status="unfulfilled",
            created_at="2025-01-15T10:00:00Z",
            customer_name="Test",
            ship_to_name="Test",
            ship_to_address1="123 Main St",
            ship_to_city="Los Angeles",
            ship_to_state="CA",
            ship_to_postal_code="90210",
            ship_to_country="US",
            items=[],
        )

        ny_order = ExternalOrder(
            platform="shopify",
            order_id="2",
            status="unfulfilled",
            created_at="2025-01-15T10:00:00Z",
            customer_name="Test",
            ship_to_name="Test",
            ship_to_address1="456 Broadway",
            ship_to_city="New York",
            ship_to_state="NY",
            ship_to_postal_code="10001",
            ship_to_country="US",
            items=[],
        )

        ca_cost = processor._estimate_shipping_cost(ca_order, "03")
        ny_cost = processor._estimate_shipping_cost(ny_order, "03")
        assert ny_cost > ca_cost

    def test_unknown_service_defaults_to_ground(self, db_session_factory, sample_order):
        """Unknown service code defaults to Ground pricing."""
        processor = CommandProcessor(db_session_factory=db_session_factory)
        unknown_cost = processor._estimate_shipping_cost(sample_order, "99")
        ground_cost = processor._estimate_shipping_cost(sample_order, "03")
        assert unknown_cost == ground_cost


class TestCommandProcessorJobNotFound:
    """Tests for edge cases with missing jobs."""

    @pytest.mark.asyncio
    async def test_process_handles_missing_job(self, db_session_factory, test_db):
        """Gracefully handles job not found."""
        processor = CommandProcessor(db_session_factory=db_session_factory)
        # Should not raise, just log error
        await processor.process("nonexistent-job-id", "Ship orders")
        # No exception means success
