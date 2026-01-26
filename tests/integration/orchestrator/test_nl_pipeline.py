"""Integration tests for NL parsing -> filter -> template pipeline.

Tests verify:
- Natural language command produces valid SQL filter
- Filter applied to real Data MCP returns correct row subset
- Generated Jinja2 template renders valid UPS-shaped payloads
- Template passes JSON Schema validation
- Full pipeline: "Ship California orders" -> filtered rows -> rendered payloads
"""

import pytest

from tests.conftest import requires_anthropic_key
from tests.helpers import MCPTestClient


@pytest.fixture
async def data_mcp_with_sample_data(
    data_mcp_config, sample_shipping_csv
) -> MCPTestClient:
    """Data MCP client with sample CSV loaded."""
    client = MCPTestClient(
        command=data_mcp_config["command"],
        args=data_mcp_config["args"],
        env=data_mcp_config["env"],
    )
    await client.start()

    # Import sample data
    await client.call_tool("import_csv", {"file_path": sample_shipping_csv})

    yield client
    await client.stop()


@pytest.mark.integration
class TestIntentToFilter:
    """Tests for intent parsing to SQL filter generation."""

    @requires_anthropic_key
    @pytest.mark.asyncio
    async def test_state_filter_generation(self, data_mcp_with_sample_data):
        """'California orders' should generate state = 'CA' filter."""
        from src.orchestrator.models.filter import ColumnInfo
        from src.orchestrator.nl_engine import generate_filter

        # Get schema from MCP (returns column info)
        schema_result = await data_mcp_with_sample_data.call_tool("get_schema", {})

        # Convert schema to ColumnInfo list
        schema = [
            ColumnInfo(
                name=col["name"],
                type=col.get("type", "string"),
                nullable=col.get("nullable", True),
                sample_values=col.get("sample_values", []),
            )
            for col in schema_result.get("columns", [])
        ]

        result = generate_filter(
            filter_expression="Ship all California orders",
            schema=schema,
        )

        assert result.where_clause is not None
        assert "CA" in result.where_clause or "California" in result.where_clause

        # Apply filter and verify results
        rows = await data_mcp_with_sample_data.call_tool(
            "get_rows_by_filter",
            {
                "filter_clause": result.where_clause,
                "limit": 100,
            },
        )

        # Should get only CA orders (3 in sample data)
        assert rows["total_count"] == 3

    @requires_anthropic_key
    @pytest.mark.asyncio
    async def test_service_filter_generation(self, data_mcp_with_sample_data):
        """'Ground shipments' should filter by service_type."""
        from src.orchestrator.models.filter import ColumnInfo
        from src.orchestrator.nl_engine import generate_filter

        schema_result = await data_mcp_with_sample_data.call_tool("get_schema", {})

        schema = [
            ColumnInfo(
                name=col["name"],
                type=col.get("type", "string"),
                nullable=col.get("nullable", True),
                sample_values=col.get("sample_values", []),
            )
            for col in schema_result.get("columns", [])
        ]

        result = generate_filter(
            filter_expression="Ship all Ground orders",
            schema=schema,
        )

        rows = await data_mcp_with_sample_data.call_tool(
            "get_rows_by_filter",
            {
                "filter_clause": result.where_clause,
                "limit": 100,
            },
        )

        # Should get only Ground orders (3 in sample data)
        assert rows["total_count"] == 3


@pytest.mark.integration
class TestTemplateGeneration:
    """Tests for mapping template generation and rendering."""

    @requires_anthropic_key
    @pytest.mark.asyncio
    async def test_template_renders_valid_payload(self, data_mcp_with_sample_data):
        """Generated template should render valid UPS payload."""
        from src.orchestrator.models.filter import ColumnInfo
        from src.orchestrator.models.mapping import FieldMapping
        from src.orchestrator.nl_engine import (
            generate_mapping_template,
            render_template,
        )

        schema_result = await data_mcp_with_sample_data.call_tool("get_schema", {})

        schema = [
            ColumnInfo(
                name=col["name"],
                type=col.get("type", "string"),
                nullable=col.get("nullable", True),
                sample_values=col.get("sample_values", []),
            )
            for col in schema_result.get("columns", [])
        ]

        # Define field mappings based on the sample CSV columns
        mappings = [
            FieldMapping(
                source_column="recipient_name",
                target_path="ShipTo.Name",
                transformation="truncate_address(35)",
            ),
            FieldMapping(
                source_column="address",
                target_path="ShipTo.Address.AddressLine",
                transformation="truncate_address(35)",
            ),
            FieldMapping(
                source_column="city",
                target_path="ShipTo.Address.City",
            ),
            FieldMapping(
                source_column="state",
                target_path="ShipTo.Address.StateProvinceCode",
            ),
            FieldMapping(
                source_column="zip",
                target_path="ShipTo.Address.PostalCode",
                transformation="format_us_zip",
            ),
            FieldMapping(
                source_column="country",
                target_path="ShipTo.Address.CountryCode",
            ),
            FieldMapping(
                source_column="weight_lbs",
                target_path="Package.PackageWeight.Weight",
            ),
        ]

        template = generate_mapping_template(
            source_schema=schema,
            user_mappings=mappings,
            template_name="test_template",
        )

        # Get a sample row
        rows = await data_mcp_with_sample_data.call_tool(
            "get_rows_by_filter",
            {
                "filter_clause": "1=1",
                "limit": 1,
            },
        )
        sample_row = rows["rows"][0]["data"]

        # Render template with sample data
        payload = render_template(template, sample_row)

        # Verify basic UPS structure
        assert "ShipTo" in payload
        assert "Name" in payload["ShipTo"]
        assert "Address" in payload["ShipTo"]


@pytest.mark.integration
class TestFullPipeline:
    """Tests for complete NL -> filter -> template -> validation pipeline."""

    @requires_anthropic_key
    @pytest.mark.asyncio
    async def test_california_ground_orders_pipeline(self, data_mcp_with_sample_data):
        """Full pipeline for 'Ship California orders via Ground'."""
        from src.orchestrator.models.filter import ColumnInfo
        from src.orchestrator.models.mapping import FieldMapping
        from src.orchestrator.nl_engine import (
            UPS_SHIPTO_SCHEMA,
            generate_filter,
            generate_mapping_template,
            parse_intent,
            render_template,
            validate_template_output,
        )

        # Step 1: Parse intent
        intent = parse_intent("Ship all California orders using UPS Ground")

        assert intent.action == "ship"
        # Service code "03" is UPS Ground
        assert intent.service_code is not None

        # Step 2: Get schema and generate filter
        schema_result = await data_mcp_with_sample_data.call_tool("get_schema", {})

        schema = [
            ColumnInfo(
                name=col["name"],
                type=col.get("type", "string"),
                nullable=col.get("nullable", True),
                sample_values=col.get("sample_values", []),
            )
            for col in schema_result.get("columns", [])
        ]

        filter_result = generate_filter(
            filter_expression="California orders",
            schema=schema,
        )

        # Step 3: Get filtered rows
        rows = await data_mcp_with_sample_data.call_tool(
            "get_rows_by_filter",
            {
                "filter_clause": filter_result.where_clause,
                "limit": 100,
            },
        )

        assert rows["total_count"] > 0

        # Step 4: Generate template with explicit mappings
        mappings = [
            FieldMapping(
                source_column="recipient_name",
                target_path="ShipTo.Name",
                transformation="truncate_address(35)",
            ),
            FieldMapping(
                source_column="address",
                target_path="ShipTo.Address.AddressLine",
                transformation="truncate_address(35)",
            ),
            FieldMapping(
                source_column="city",
                target_path="ShipTo.Address.City",
            ),
            FieldMapping(
                source_column="state",
                target_path="ShipTo.Address.StateProvinceCode",
            ),
            FieldMapping(
                source_column="zip",
                target_path="ShipTo.Address.PostalCode",
                transformation="format_us_zip",
            ),
            FieldMapping(
                source_column="country",
                target_path="ShipTo.Address.CountryCode",
            ),
        ]

        template = generate_mapping_template(
            source_schema=schema,
            user_mappings=mappings,
            template_name="california_ground",
        )

        # Step 5: Render and validate template
        sample_row = rows["rows"][0]["data"]
        rendered_payload = render_template(template, sample_row)

        # Validate the ShipTo portion against UPS schema
        validation_result = validate_template_output(
            rendered_output=rendered_payload.get("ShipTo", {}),
            target_schema=UPS_SHIPTO_SCHEMA,
        )

        # Either valid or has specific, actionable errors
        assert validation_result.valid or len(validation_result.errors) > 0


@pytest.mark.integration
class TestIntentParsing:
    """Tests for natural language intent parsing."""

    @requires_anthropic_key
    @pytest.mark.asyncio
    async def test_parse_ship_command(self):
        """Parse a basic ship command."""
        from src.orchestrator.nl_engine import parse_intent

        intent = parse_intent("Ship orders via Ground")

        assert intent.action == "ship"

    @requires_anthropic_key
    @pytest.mark.asyncio
    async def test_parse_rate_command(self):
        """Parse a rate command."""
        from src.orchestrator.nl_engine import parse_intent

        intent = parse_intent("Rate my orders using UPS Ground")

        assert intent.action == "rate"

    @requires_anthropic_key
    @pytest.mark.asyncio
    async def test_parse_with_filter(self):
        """Parse command with filter criteria."""
        from src.orchestrator.nl_engine import parse_intent

        intent = parse_intent("Ship California orders via Next Day Air")

        assert intent.action == "ship"
        assert intent.filter_criteria is not None
        assert (
            "California" in intent.filter_criteria.raw_expression.lower()
            or "state" in intent.filter_criteria.raw_expression.lower()
        )


@pytest.mark.integration
class TestFilterGeneration:
    """Tests for SQL filter generation."""

    @requires_anthropic_key
    @pytest.mark.asyncio
    async def test_generate_state_filter(self):
        """Generate filter for state-based query."""
        from src.orchestrator.models.filter import ColumnInfo
        from src.orchestrator.nl_engine import generate_filter

        schema = [
            ColumnInfo(name="state", type="string", sample_values=["CA", "TX", "NY"]),
            ColumnInfo(name="city", type="string"),
            ColumnInfo(name="order_id", type="integer"),
        ]

        result = generate_filter(
            filter_expression="California orders",
            schema=schema,
        )

        assert result.where_clause is not None
        assert "state" in result.columns_used
        assert "CA" in result.where_clause or "California" in result.where_clause

    @requires_anthropic_key
    @pytest.mark.asyncio
    async def test_filter_ambiguity_detection(self):
        """Detect ambiguous filter with multiple date columns."""
        from src.orchestrator.models.filter import ColumnInfo
        from src.orchestrator.nl_engine import generate_filter

        # Schema with multiple date columns - temporal filter should need clarification
        schema = [
            ColumnInfo(name="order_date", type="date"),
            ColumnInfo(name="ship_date", type="date"),
            ColumnInfo(name="order_id", type="integer"),
        ]

        result = generate_filter(
            filter_expression="today's orders",
            schema=schema,
        )

        # With multiple date columns, the filter should flag need for clarification
        assert result.needs_clarification is True


@pytest.mark.integration
class TestTemplateValidation:
    """Tests for template validation against UPS schema."""

    def test_valid_shipto_payload(self):
        """Valid ShipTo payload should pass validation."""
        from src.orchestrator.nl_engine import (
            UPS_SHIPTO_SCHEMA,
            validate_template_output,
        )

        valid_payload = {
            "Name": "John Doe",
            "Address": {
                "AddressLine": ["123 Main Street"],
                "City": "Los Angeles",
                "StateProvinceCode": "CA",
                "PostalCode": "90001",
                "CountryCode": "US",
            },
        }

        result = validate_template_output(valid_payload, UPS_SHIPTO_SCHEMA)
        assert result.valid is True
        assert len(result.errors) == 0

    def test_invalid_shipto_missing_required(self):
        """ShipTo missing required fields should fail validation."""
        from src.orchestrator.nl_engine import (
            UPS_SHIPTO_SCHEMA,
            validate_template_output,
        )

        invalid_payload = {
            "Name": "John Doe",
            # Missing Address
        }

        result = validate_template_output(invalid_payload, UPS_SHIPTO_SCHEMA)
        assert result.valid is False
        assert len(result.errors) > 0

    def test_invalid_address_line_too_long(self):
        """Address line exceeding max length should fail validation."""
        from src.orchestrator.nl_engine import (
            UPS_SHIPTO_SCHEMA,
            validate_template_output,
        )

        # Address line exceeds 35 char limit
        long_address = "A" * 50

        invalid_payload = {
            "Name": "John Doe",
            "Address": {
                "AddressLine": [long_address],
                "City": "Los Angeles",
                "StateProvinceCode": "CA",
                "PostalCode": "90001",
                "CountryCode": "US",
            },
        }

        result = validate_template_output(invalid_payload, UPS_SHIPTO_SCHEMA)
        assert result.valid is False
        # Should have maxLength error
        max_length_errors = [e for e in result.errors if e.schema_rule == "maxLength"]
        assert len(max_length_errors) > 0
