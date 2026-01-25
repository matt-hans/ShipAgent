"""Unit tests for batch preview generation.

Tests cover:
- Small batch preview (all rows detailed)
- Large batch preview (20 detailed, rest estimated)
- Name truncation
- Warning capture from quotes
- Error handling
- Empty batch handling
- Cost calculation accuracy
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.orchestrator.batch.models import BatchPreview, PreviewRow
from src.orchestrator.batch.preview import PreviewGenerator


def make_row(
    row_number: int, name: str, city: str, state: str, weight: float = 5.0
) -> dict[str, Any]:
    """Create a test row with standard structure."""
    return {
        "row_number": row_number,
        "data": {
            "recipient_name": name,
            "city": city,
            "state": state,
            "weight": weight,
            "address1": "123 Main St",
            "zip": "90001",
        },
    }


def make_data_result(
    rows: list[dict[str, Any]], total_count: int | None = None
) -> dict[str, Any]:
    """Create a mock Data MCP result."""
    return {
        "rows": rows,
        "total_count": total_count if total_count is not None else len(rows),
    }


def make_quote_result(
    amount: str, warnings: list[str] | None = None, address_correction: bool = False
) -> dict[str, Any]:
    """Create a mock UPS rate quote result."""
    result: dict[str, Any] = {
        "totalCharges": {"amount": amount},
    }
    if warnings:
        result["warnings"] = warnings
    if address_correction:
        result["addressCorrection"] = True
    return result


# Simple template for testing
SIMPLE_TEMPLATE = """{
    "ShipTo": {
        "Name": "{{ row.recipient_name }}",
        "Address": {
            "City": "{{ row.city }}",
            "StateProvinceCode": "{{ row.state }}",
            "PostalCode": "{{ row.zip }}"
        }
    },
    "Service": {"Code": "03"},
    "Package": {"Weight": {"UnitOfMeasurement": {"Code": "LBS"}, "Weight": "{{ row.weight }}"}}
}"""

SHIPPER_INFO = {
    "Name": "Test Shipper",
    "Address": {"City": "Los Angeles", "StateProvinceCode": "CA", "PostalCode": "90001"},
}


class TestPreviewGeneratorSmallBatch:
    """Tests for small batches (all rows detailed)."""

    async def test_generate_preview_small_batch(self) -> None:
        """Test preview with 5 rows total - all get rate quotes."""
        rows = [
            make_row(1, "John Doe", "Seattle", "WA"),
            make_row(2, "Jane Smith", "Portland", "OR"),
            make_row(3, "Bob Wilson", "Denver", "CO"),
            make_row(4, "Alice Brown", "Phoenix", "AZ"),
            make_row(5, "Charlie Davis", "Houston", "TX"),
        ]

        data_mcp = AsyncMock(return_value=make_data_result(rows))
        ups_mcp = AsyncMock(return_value=make_quote_result("12.50"))

        generator = PreviewGenerator(data_mcp, ups_mcp)
        preview = await generator.generate_preview(
            job_id="job-123",
            filter_clause="state != 'CA'",
            mapping_template=SIMPLE_TEMPLATE,
            shipper_info=SHIPPER_INFO,
        )

        assert preview.job_id == "job-123"
        assert preview.total_rows == 5
        assert len(preview.preview_rows) == 5
        assert preview.additional_rows == 0

        # All rows get $12.50 quote = 1250 cents each
        assert preview.total_estimated_cost_cents == 5 * 1250

    async def test_preview_row_contains_correct_data(self) -> None:
        """Test that preview rows contain correct extracted data."""
        rows = [make_row(1, "John Doe", "Seattle", "WA")]

        data_mcp = AsyncMock(return_value=make_data_result(rows))
        ups_mcp = AsyncMock(return_value=make_quote_result("15.00"))

        generator = PreviewGenerator(data_mcp, ups_mcp)
        preview = await generator.generate_preview(
            job_id="job-123",
            filter_clause="1=1",
            mapping_template=SIMPLE_TEMPLATE,
            shipper_info=SHIPPER_INFO,
        )

        row = preview.preview_rows[0]
        assert row.row_number == 1
        assert row.recipient_name == "John Doe"
        assert row.city_state == "Seattle, WA"
        assert row.service == "Ground"
        assert row.estimated_cost_cents == 1500
        assert row.warnings == []


class TestPreviewGeneratorLargeBatch:
    """Tests for large batches (>20 rows)."""

    async def test_generate_preview_large_batch(self) -> None:
        """Test preview with 50 rows - only first 20 detailed."""
        # Create 20 rows (the maximum we'd get from the query)
        rows = [make_row(i, f"Person {i}", "City", "ST") for i in range(1, 21)]

        # Data MCP returns 20 rows but indicates 50 total
        data_mcp = AsyncMock(return_value=make_data_result(rows, total_count=50))
        ups_mcp = AsyncMock(return_value=make_quote_result("10.00"))

        generator = PreviewGenerator(data_mcp, ups_mcp)
        preview = await generator.generate_preview(
            job_id="job-large",
            filter_clause="active = true",
            mapping_template=SIMPLE_TEMPLATE,
            shipper_info=SHIPPER_INFO,
        )

        assert preview.total_rows == 50
        assert len(preview.preview_rows) == 20
        assert preview.additional_rows == 30

        # 20 rows at $10 = 20,000 cents
        # Average = 1000 cents
        # 30 additional * 1000 = 30,000 cents estimated
        # Total = 50,000 cents
        assert preview.total_estimated_cost_cents == 50000

    async def test_large_batch_average_estimation(self) -> None:
        """Test that additional rows are estimated using average cost."""
        rows = [make_row(i, f"Person {i}", "City", "ST") for i in range(1, 21)]

        data_mcp = AsyncMock(return_value=make_data_result(rows, total_count=100))

        # Variable costs: first 10 at $10, next 10 at $20
        # Average = ($10 * 10 + $20 * 10) / 20 = $15
        call_count = 0

        async def variable_quote(*args: Any, **kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count <= 10:
                return make_quote_result("10.00")
            else:
                return make_quote_result("20.00")

        ups_mcp = AsyncMock(side_effect=variable_quote)

        generator = PreviewGenerator(data_mcp, ups_mcp)
        preview = await generator.generate_preview(
            job_id="job-var",
            filter_clause="1=1",
            mapping_template=SIMPLE_TEMPLATE,
            shipper_info=SHIPPER_INFO,
        )

        # 20 quoted: 10*1000 + 10*2000 = 30000 cents
        # Average = 30000/20 = 1500 cents
        # 80 additional * 1500 = 120000 cents
        # Total = 150000 cents
        assert preview.total_estimated_cost_cents == 150000


class TestPreviewTruncation:
    """Tests for name truncation."""

    async def test_preview_truncates_long_names(self) -> None:
        """Test that recipient names longer than 20 chars are truncated."""
        rows = [make_row(1, "Alexander Christopher Johnson III", "Seattle", "WA")]

        data_mcp = AsyncMock(return_value=make_data_result(rows))
        ups_mcp = AsyncMock(return_value=make_quote_result("12.50"))

        generator = PreviewGenerator(data_mcp, ups_mcp)
        preview = await generator.generate_preview(
            job_id="job-123",
            filter_clause="1=1",
            mapping_template=SIMPLE_TEMPLATE,
            shipper_info=SHIPPER_INFO,
        )

        row = preview.preview_rows[0]
        # Should truncate at word boundary
        assert len(row.recipient_name) <= 20
        assert row.recipient_name == "Alexander"

    async def test_truncate_at_word_boundary(self) -> None:
        """Test that truncation happens at word boundary."""
        rows = [make_row(1, "John Michael Christopher Doe", "Seattle", "WA")]

        data_mcp = AsyncMock(return_value=make_data_result(rows))
        ups_mcp = AsyncMock(return_value=make_quote_result("12.50"))

        generator = PreviewGenerator(data_mcp, ups_mcp)
        preview = await generator.generate_preview(
            job_id="job-123",
            filter_clause="1=1",
            mapping_template=SIMPLE_TEMPLATE,
            shipper_info=SHIPPER_INFO,
        )

        row = preview.preview_rows[0]
        # "John Michael" = 12 chars, fits
        # "John Michael Christopher" = 24 chars, too long
        # Should truncate to "John Michael"
        assert row.recipient_name == "John Michael"

    async def test_short_names_not_truncated(self) -> None:
        """Test that short names are not modified."""
        rows = [make_row(1, "Jo", "Seattle", "WA")]

        data_mcp = AsyncMock(return_value=make_data_result(rows))
        ups_mcp = AsyncMock(return_value=make_quote_result("12.50"))

        generator = PreviewGenerator(data_mcp, ups_mcp)
        preview = await generator.generate_preview(
            job_id="job-123",
            filter_clause="1=1",
            mapping_template=SIMPLE_TEMPLATE,
            shipper_info=SHIPPER_INFO,
        )

        assert preview.preview_rows[0].recipient_name == "Jo"


class TestPreviewWarnings:
    """Tests for warning capture from quote responses."""

    async def test_preview_captures_address_correction_warning(self) -> None:
        """Test that address correction indicator is captured as warning."""
        rows = [make_row(1, "John Doe", "Seattle", "WA")]

        data_mcp = AsyncMock(return_value=make_data_result(rows))
        ups_mcp = AsyncMock(return_value=make_quote_result("12.50", address_correction=True))

        generator = PreviewGenerator(data_mcp, ups_mcp)
        preview = await generator.generate_preview(
            job_id="job-123",
            filter_clause="1=1",
            mapping_template=SIMPLE_TEMPLATE,
            shipper_info=SHIPPER_INFO,
        )

        row = preview.preview_rows[0]
        assert len(row.warnings) == 1
        assert "Address correction suggested" in row.warnings

    async def test_preview_captures_warnings_array(self) -> None:
        """Test that warnings array from response is captured."""
        rows = [make_row(1, "John Doe", "Seattle", "WA")]

        data_mcp = AsyncMock(return_value=make_data_result(rows))
        ups_mcp = AsyncMock(
            return_value=make_quote_result(
                "12.50", warnings=["Residential surcharge applied", "Delivery area surcharge"]
            )
        )

        generator = PreviewGenerator(data_mcp, ups_mcp)
        preview = await generator.generate_preview(
            job_id="job-123",
            filter_clause="1=1",
            mapping_template=SIMPLE_TEMPLATE,
            shipper_info=SHIPPER_INFO,
        )

        row = preview.preview_rows[0]
        assert len(row.warnings) == 2
        assert "Residential surcharge applied" in row.warnings
        assert "Delivery area surcharge" in row.warnings

    async def test_preview_counts_rows_with_warnings(self) -> None:
        """Test that rows_with_warnings count is correct."""
        rows = [
            make_row(1, "John Doe", "Seattle", "WA"),
            make_row(2, "Jane Smith", "Portland", "OR"),
            make_row(3, "Bob Wilson", "Denver", "CO"),
        ]

        data_mcp = AsyncMock(return_value=make_data_result(rows))

        call_count = 0

        async def alternating_warnings(*args: Any, **kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count in [1, 3]:  # Rows 1 and 3 have warnings
                return make_quote_result("12.50", address_correction=True)
            return make_quote_result("12.50")

        ups_mcp = AsyncMock(side_effect=alternating_warnings)

        generator = PreviewGenerator(data_mcp, ups_mcp)
        preview = await generator.generate_preview(
            job_id="job-123",
            filter_clause="1=1",
            mapping_template=SIMPLE_TEMPLATE,
            shipper_info=SHIPPER_INFO,
        )

        assert preview.rows_with_warnings == 2


class TestPreviewErrorHandling:
    """Tests for error handling."""

    async def test_preview_handles_quote_error(self) -> None:
        """Test that quote errors are propagated."""
        rows = [make_row(1, "John Doe", "Seattle", "WA")]

        data_mcp = AsyncMock(return_value=make_data_result(rows))
        ups_mcp = AsyncMock(side_effect=RuntimeError("UPS API timeout"))

        generator = PreviewGenerator(data_mcp, ups_mcp)

        with pytest.raises(RuntimeError) as exc_info:
            await generator.generate_preview(
                job_id="job-123",
                filter_clause="1=1",
                mapping_template=SIMPLE_TEMPLATE,
                shipper_info=SHIPPER_INFO,
            )

        assert "Failed to generate preview for row 1" in str(exc_info.value)

    async def test_preview_handles_data_mcp_error(self) -> None:
        """Test that Data MCP errors are propagated."""
        data_mcp = AsyncMock(side_effect=RuntimeError("Database connection failed"))
        ups_mcp = AsyncMock()

        generator = PreviewGenerator(data_mcp, ups_mcp)

        with pytest.raises(RuntimeError) as exc_info:
            await generator.generate_preview(
                job_id="job-123",
                filter_clause="1=1",
                mapping_template=SIMPLE_TEMPLATE,
                shipper_info=SHIPPER_INFO,
            )

        assert "Database connection failed" in str(exc_info.value)


class TestPreviewEmptyBatch:
    """Tests for empty batch handling."""

    async def test_preview_empty_batch(self) -> None:
        """Test preview with 0 rows matching filter."""
        data_mcp = AsyncMock(return_value=make_data_result([], total_count=0))
        ups_mcp = AsyncMock()

        generator = PreviewGenerator(data_mcp, ups_mcp)
        preview = await generator.generate_preview(
            job_id="job-empty",
            filter_clause="state = 'XX'",
            mapping_template=SIMPLE_TEMPLATE,
            shipper_info=SHIPPER_INFO,
        )

        assert preview.job_id == "job-empty"
        assert preview.total_rows == 0
        assert preview.preview_rows == []
        assert preview.additional_rows == 0
        assert preview.total_estimated_cost_cents == 0
        assert preview.rows_with_warnings == 0

        # UPS MCP should not be called for empty batch
        ups_mcp.assert_not_called()


class TestPreviewCostCalculation:
    """Tests for cost calculation accuracy."""

    async def test_preview_cost_conversion_to_cents(self) -> None:
        """Test that string amounts are correctly converted to cents."""
        rows = [make_row(1, "John Doe", "Seattle", "WA")]

        data_mcp = AsyncMock(return_value=make_data_result(rows))
        ups_mcp = AsyncMock(return_value=make_quote_result("123.45"))

        generator = PreviewGenerator(data_mcp, ups_mcp)
        preview = await generator.generate_preview(
            job_id="job-123",
            filter_clause="1=1",
            mapping_template=SIMPLE_TEMPLATE,
            shipper_info=SHIPPER_INFO,
        )

        assert preview.preview_rows[0].estimated_cost_cents == 12345

    async def test_preview_cost_handles_whole_numbers(self) -> None:
        """Test that whole number amounts are correctly converted."""
        rows = [make_row(1, "John Doe", "Seattle", "WA")]

        data_mcp = AsyncMock(return_value=make_data_result(rows))
        ups_mcp = AsyncMock(return_value=make_quote_result("100.00"))

        generator = PreviewGenerator(data_mcp, ups_mcp)
        preview = await generator.generate_preview(
            job_id="job-123",
            filter_clause="1=1",
            mapping_template=SIMPLE_TEMPLATE,
            shipper_info=SHIPPER_INFO,
        )

        assert preview.preview_rows[0].estimated_cost_cents == 10000

    async def test_preview_cost_handles_single_cent(self) -> None:
        """Test that single cent amounts are correctly converted."""
        rows = [make_row(1, "John Doe", "Seattle", "WA")]

        data_mcp = AsyncMock(return_value=make_data_result(rows))
        ups_mcp = AsyncMock(return_value=make_quote_result("0.01"))

        generator = PreviewGenerator(data_mcp, ups_mcp)
        preview = await generator.generate_preview(
            job_id="job-123",
            filter_clause="1=1",
            mapping_template=SIMPLE_TEMPLATE,
            shipper_info=SHIPPER_INFO,
        )

        assert preview.preview_rows[0].estimated_cost_cents == 1

    async def test_preview_total_cost_aggregation(self) -> None:
        """Test that total cost correctly sums individual row costs."""
        rows = [
            make_row(1, "John Doe", "Seattle", "WA"),
            make_row(2, "Jane Smith", "Portland", "OR"),
            make_row(3, "Bob Wilson", "Denver", "CO"),
        ]

        data_mcp = AsyncMock(return_value=make_data_result(rows))

        costs = ["10.00", "15.50", "8.25"]
        call_count = 0

        async def varied_costs(*args: Any, **kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            result = make_quote_result(costs[call_count])
            call_count += 1
            return result

        ups_mcp = AsyncMock(side_effect=varied_costs)

        generator = PreviewGenerator(data_mcp, ups_mcp)
        preview = await generator.generate_preview(
            job_id="job-123",
            filter_clause="1=1",
            mapping_template=SIMPLE_TEMPLATE,
            shipper_info=SHIPPER_INFO,
        )

        # 1000 + 1550 + 825 = 3375 cents
        assert preview.total_estimated_cost_cents == 3375

    async def test_preview_handles_missing_cost(self) -> None:
        """Test that missing cost defaults to 0."""
        rows = [make_row(1, "John Doe", "Seattle", "WA")]

        data_mcp = AsyncMock(return_value=make_data_result(rows))
        ups_mcp = AsyncMock(return_value={"totalCharges": {}})  # Missing amount

        generator = PreviewGenerator(data_mcp, ups_mcp)
        preview = await generator.generate_preview(
            job_id="job-123",
            filter_clause="1=1",
            mapping_template=SIMPLE_TEMPLATE,
            shipper_info=SHIPPER_INFO,
        )

        assert preview.preview_rows[0].estimated_cost_cents == 0


class TestPreviewMcpCalls:
    """Tests for MCP call parameters."""

    async def test_data_mcp_called_with_correct_params(self) -> None:
        """Test that Data MCP is called with correct parameters."""
        data_mcp = AsyncMock(return_value=make_data_result([]))
        ups_mcp = AsyncMock()

        generator = PreviewGenerator(data_mcp, ups_mcp)
        await generator.generate_preview(
            job_id="job-123",
            filter_clause="state = 'CA' AND status = 'pending'",
            mapping_template=SIMPLE_TEMPLATE,
            shipper_info=SHIPPER_INFO,
        )

        data_mcp.assert_called_once_with(
            "get_rows_by_filter",
            {
                "where_clause": "state = 'CA' AND status = 'pending'",
                "limit": 20,
                "offset": 0,
            },
        )

    async def test_ups_mcp_called_for_each_row(self) -> None:
        """Test that UPS MCP is called once per row."""
        rows = [
            make_row(1, "John Doe", "Seattle", "WA"),
            make_row(2, "Jane Smith", "Portland", "OR"),
        ]

        data_mcp = AsyncMock(return_value=make_data_result(rows))
        ups_mcp = AsyncMock(return_value=make_quote_result("12.50"))

        generator = PreviewGenerator(data_mcp, ups_mcp)
        await generator.generate_preview(
            job_id="job-123",
            filter_clause="1=1",
            mapping_template=SIMPLE_TEMPLATE,
            shipper_info=SHIPPER_INFO,
        )

        assert ups_mcp.call_count == 2
