"""Command processor for NL shipping commands.

This module bridges the FastAPI command endpoint to the NL pipeline,
processing natural language commands into ready-to-preview jobs with
JobRows and real UPS rate quotes.

The CommandProcessor:
1. Parses intent via parse_intent()
2. Generates SQL filter via generate_filter()
3. Fetches orders from connected platforms matching the filter
4. Creates JobRows with placeholder costs
5. Calls BatchEngine.preview() for real UPS rate quotes (via MCP)
6. Updates row costs and sets Job total_rows count

Per CONTEXT.md Decision 1:
- LLM acts as Configuration Engine, not Data Pipe
- LLM interprets user intent and generates transformation rules
- Deterministic code executes those rules on actual shipping data
"""

import hashlib
import json
import logging
import os
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import Job, JobRow, RowStatus
from src.services.batch_engine import BatchEngine
from src.services.column_mapping import (
    apply_mapping,
    auto_map_columns,
    translate_service_name,
    validate_mapping,
)
from src.services.data_source_service import DataSourceService
from src.services.ups_payload_builder import build_shipper_from_env
from src.services.ups_service import UPSService
from src.mcp.external_sources.models import ExternalOrder, OrderFilters
from src.orchestrator.models.filter import ColumnInfo, SQLFilterResult
from src.orchestrator.nl_engine.filter_generator import (
    FilterGenerationError,
    generate_filter,
)
from src.orchestrator.nl_engine.intent_parser import IntentParseError, parse_intent

logger = logging.getLogger(__name__)


# Schema definition for Shopify orders - used for grounding filter generation
# Comprehensive schema covering ALL available order fields
SHOPIFY_ORDER_SCHEMA = [
    # Order identifiers
    ColumnInfo(
        name="order_id",
        type="string",
        nullable=False,
        sample_values=["12345678901", "12345678902"],
    ),
    ColumnInfo(
        name="order_number",
        type="string",
        nullable=True,
        sample_values=["1001", "1002", "1003"],
    ),
    ColumnInfo(
        name="status",
        type="string",
        nullable=False,
        sample_values=["paid/unfulfilled", "paid/fulfilled", "pending/unfulfilled"],
    ),
    ColumnInfo(
        name="created_at",
        type="datetime",
        nullable=False,
        sample_values=["2025-01-15T10:30:00Z", "2025-01-16T14:20:00Z"],
    ),
    # Customer info (person who PLACED the order)
    ColumnInfo(
        name="customer_name",
        type="string",
        nullable=False,
        sample_values=["John Smith", "Jane Doe", "Arely Crooks"],
    ),
    ColumnInfo(
        name="customer_email",
        type="string",
        nullable=True,
        sample_values=["john@example.com", "jane@example.com"],
    ),
    # Shipping recipient info (person who RECEIVES the package)
    ColumnInfo(
        name="ship_to_name",
        type="string",
        nullable=False,
        sample_values=["John Smith", "Jane Doe", "Kathleen Nolan"],
    ),
    ColumnInfo(
        name="ship_to_company",
        type="string",
        nullable=True,
        sample_values=["Acme Corp", "TechStart Inc"],
    ),
    ColumnInfo(
        name="ship_to_address1",
        type="string",
        nullable=False,
        sample_values=["123 Main St", "456 Oak Ave", "100 Robinson Centre Dr"],
    ),
    ColumnInfo(
        name="ship_to_address2",
        type="string",
        nullable=True,
        sample_values=["Apt 4B", "Suite 200", "Floor 3"],
    ),
    ColumnInfo(
        name="ship_to_city",
        type="string",
        nullable=False,
        sample_values=["Los Angeles", "San Francisco", "New York", "Pittsburgh"],
    ),
    ColumnInfo(
        name="ship_to_state",
        type="string",
        nullable=False,
        sample_values=["CA", "NY", "TX", "FL", "WA", "PA"],
    ),
    ColumnInfo(
        name="ship_to_postal_code",
        type="string",
        nullable=False,
        sample_values=["90210", "94102", "10001", "15205"],
    ),
    ColumnInfo(
        name="ship_to_country",
        type="string",
        nullable=False,
        sample_values=["US", "CA"],
    ),
    ColumnInfo(
        name="ship_to_phone",
        type="string",
        nullable=True,
        sample_values=["555-123-4567", "(212) 555-1234"],
    ),
    # Financial
    ColumnInfo(
        name="total_price",
        type="numeric",
        nullable=True,
        sample_values=["49.99", "149.50", "250.00"],
    ),
    # Status breakdown (standalone)
    ColumnInfo(
        name="financial_status",
        type="string",
        nullable=True,
        sample_values=["paid", "pending", "refunded", "authorized"],
    ),
    ColumnInfo(
        name="fulfillment_status",
        type="string",
        nullable=True,
        sample_values=["unfulfilled", "fulfilled", "partial"],
    ),
    # Tags
    ColumnInfo(
        name="tags",
        type="string",
        nullable=True,
        sample_values=["VIP", "wholesale", "priority", "fragile"],
    ),
    # Weight
    ColumnInfo(
        name="total_weight_grams",
        type="numeric",
        nullable=True,
        sample_values=[100, 500, 2000, 5000],
    ),
    # Shipping method
    ColumnInfo(
        name="shipping_method",
        type="string",
        nullable=True,
        sample_values=["Standard Shipping", "Express", "Economy"],
    ),
    # Item count
    ColumnInfo(
        name="item_count",
        type="integer",
        nullable=True,
        sample_values=[1, 3, 5, 10],
    ),
]


def _duckdb_type_to_column_type(duckdb_type: str) -> str:
    """Map DuckDB column types to ColumnInfo type strings.

    Args:
        duckdb_type: DuckDB type string (e.g., 'VARCHAR', 'BIGINT', 'DOUBLE').

    Returns:
        ColumnInfo-compatible type string (e.g., 'string', 'integer', 'numeric').
    """
    upper = duckdb_type.upper()
    if upper in ("VARCHAR", "TEXT", "CHAR"):
        return "string"
    elif upper in ("BIGINT", "INTEGER", "SMALLINT", "TINYINT", "HUGEINT"):
        return "integer"
    elif upper in ("DOUBLE", "FLOAT", "REAL", "DECIMAL", "NUMERIC"):
        return "numeric"
    elif upper in ("DATE",):
        return "date"
    elif upper in ("TIMESTAMP", "TIMESTAMPTZ", "TIMESTAMP WITH TIME ZONE"):
        return "datetime"
    elif upper in ("BOOLEAN",):
        return "boolean"
    return "string"


# Build column type registry from schema for evaluator dispatch
_COLUMN_TYPES: dict[str, str] = {col.name: col.type for col in SHOPIFY_ORDER_SCHEMA}

# Columns requiring uppercase normalization for comparison
_UPPER_COLUMNS = frozenset({"ship_to_state", "ship_to_country"})

# Columns requiring phone-digit normalization
_PHONE_COLUMNS = frozenset({"ship_to_phone"})


def compute_order_checksum(order: ExternalOrder) -> str:
    """Compute SHA-256 checksum of order data for integrity verification.

    Args:
        order: The ExternalOrder to checksum.

    Returns:
        Hex-encoded SHA-256 hash of the order's key fields.
    """
    # Create deterministic JSON representation of key fields
    data = {
        "order_id": order.order_id,
        "ship_to_name": order.ship_to_name,
        "ship_to_address1": order.ship_to_address1,
        "ship_to_city": order.ship_to_city,
        "ship_to_state": order.ship_to_state,
        "ship_to_postal_code": order.ship_to_postal_code,
    }
    json_str = json.dumps(data, sort_keys=True)
    return hashlib.sha256(json_str.encode()).hexdigest()


def apply_filter_to_orders(
    orders: list[ExternalOrder],
    filter_result: SQLFilterResult,
) -> list[ExternalOrder]:
    """Apply SQL-like filter to orders in memory.

    This function evaluates the generated SQL WHERE clause against each order.
    Since we're working with in-memory data, we translate common SQL patterns
    to Python predicates.

    Args:
        orders: List of orders to filter.
        filter_result: The generated SQL filter.

    Returns:
        List of orders matching the filter criteria.
    """
    where_clause = filter_result.where_clause.strip()

    # Handle empty or trivial filters
    if not where_clause or where_clause == "1=1" or where_clause == "TRUE":
        return orders

    filtered = []
    for order in orders:
        if _order_matches_filter(order, where_clause):
            filtered.append(order)

    return filtered


def _split_compound_clause(where_clause: str) -> tuple[str, list[str]]:
    """Split a WHERE clause on top-level AND/OR operators.

    Handles parenthesized sub-expressions by stripping outer parens first.
    Returns the operator ('AND', 'OR', or 'SINGLE') and a list of sub-clauses.

    Args:
        where_clause: SQL WHERE clause (without 'WHERE' keyword).

    Returns:
        Tuple of (operator, sub_clauses).
    """
    clause = where_clause.strip()

    # Strip outer parentheses if the entire clause is wrapped
    if clause.startswith("(") and clause.endswith(")"):
        depth = 0
        all_wrapped = True
        for i, ch in enumerate(clause):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if depth == 0 and i < len(clause) - 1:
                all_wrapped = False
                break
        if all_wrapped:
            clause = clause[1:-1].strip()

    # Split on top-level OR first (lower precedence), then AND
    for operator in ("OR", "AND"):
        parts = _split_on_operator(clause, operator)
        if len(parts) > 1:
            return (operator, [p.strip() for p in parts])

    return ("SINGLE", [clause])


def _split_on_operator(clause: str, operator: str) -> list[str]:
    """Split clause on a SQL boolean operator, respecting parentheses.

    Only splits on the operator when it appears at the top level (not inside
    parentheses) and is surrounded by whitespace.

    Args:
        clause: SQL expression to split.
        operator: 'AND' or 'OR'.

    Returns:
        List of sub-expressions. Length 1 if operator not found at top level.
    """
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    tokens = clause.split()
    i = 0
    while i < len(tokens):
        token = tokens[i]
        # Track parenthesis depth
        depth += token.count("(") - token.count(")")

        if depth == 0 and token.upper() == operator:
            parts.append(" ".join(current))
            current = []
        else:
            current.append(token)
        i += 1

    if current:
        parts.append(" ".join(current))

    return parts


def _eval_null_clause(clause_lower: str, col_name: str, order_value: Any) -> bool | None:
    """Handle IS NULL / IS NOT NULL checks.

    Args:
        clause_lower: Lowercased WHERE clause.
        col_name: Column name to check.
        order_value: The order's value for the column.

    Returns:
        True/False if it's a null check, None if not a null check.
    """
    col_null_pattern = f"{col_name} is not null"
    if col_null_pattern in clause_lower:
        return order_value is not None and order_value != ""
    col_null_pattern = f"{col_name} is null"
    if col_null_pattern in clause_lower:
        return order_value is None or order_value == ""
    return None


def _eval_string_clause(
    where_clause: str,
    col_name: str,
    order_value: str | None,
) -> bool:
    """Evaluate string column: exact match (=) and LIKE patterns.

    Handles case normalization based on column type:
    - UPPER_COLUMNS: uppercase comparison (state codes, country codes)
    - PHONE_COLUMNS: digit-only comparison
    - Default: case-insensitive lowercase comparison

    Args:
        where_clause: Original WHERE clause (preserves case for regex).
        col_name: Column name being evaluated.
        order_value: The order's string value for this column.

    Returns:
        True if the clause matches.
    """
    import re

    value = order_value or ""

    # Determine normalization strategy
    if col_name in _PHONE_COLUMNS:
        # Phone: try exact then LIKE with digit normalization
        match = re.search(
            rf"{col_name}\s*=\s*['\"]([^'\"]+)['\"]",
            where_clause, re.IGNORECASE,
        )
        if match:
            target = match.group(1)
            target_digits = re.sub(r"\D", "", target)
            value_digits = re.sub(r"\D", "", value)
            return value_digits == target_digits or value == target

        like_match = re.search(
            rf"{col_name}\s+like\s+['\"]%?([^%'\"]+)%?['\"]",
            where_clause, re.IGNORECASE,
        )
        if like_match:
            target = like_match.group(1)
            target_digits = re.sub(r"\D", "", target)
            value_digits = re.sub(r"\D", "", value)
            return target_digits in value_digits or target in value
        return True  # Fallthrough

    # Standard string: try LIKE first (check presence of LIKE keyword)
    clause_lower = where_clause.lower()
    if "like" in clause_lower:
        like_match = re.search(
            rf"{col_name}\s+like\s+['\"]%?([^%'\"]+)%?['\"]",
            where_clause, re.IGNORECASE,
        )
        if like_match:
            target = like_match.group(1)
            if col_name in _UPPER_COLUMNS:
                return target.upper() in value.upper()
            return target.lower() in value.lower()

    # Exact match — try quoted value first, then unquoted
    match = re.search(
        rf"{col_name}\s*=\s*['\"]([^'\"]+)['\"]",
        where_clause, re.IGNORECASE,
    )
    if not match:
        # Unquoted value (e.g. column = value)
        match = re.search(
            rf"{col_name}\s*=\s*(\S+)",
            where_clause, re.IGNORECASE,
        )
    if match:
        target = match.group(1).strip()
        if col_name in _UPPER_COLUMNS:
            return value.upper() == target.upper()
        return value.lower() == target.lower()

    return True  # Fallthrough


def _eval_numeric_clause(
    where_clause: str,
    col_name: str,
    order_value: Any,
) -> bool:
    """Evaluate numeric column: >, >=, <, <=, =, !=.

    Args:
        where_clause: Original WHERE clause.
        col_name: Column name being evaluated.
        order_value: The order's value for this column.

    Returns:
        True if the clause matches.
    """
    import re

    numeric_match = re.search(
        rf"{col_name}\s*([><=!]+)\s*['\"]?([0-9.]+)['\"]?",
        where_clause, re.IGNORECASE,
    )
    if not numeric_match:
        return True  # Fallthrough

    operator = numeric_match.group(1)
    target_value = float(numeric_match.group(2))
    try:
        val = float(order_value) if order_value is not None else 0.0
        if operator == ">":
            return val > target_value
        elif operator == ">=":
            return val >= target_value
        elif operator == "<":
            return val < target_value
        elif operator == "<=":
            return val <= target_value
        elif operator in ("=", "=="):
            return val == target_value
        elif operator in ("!=", "<>"):
            return val != target_value
    except (ValueError, TypeError):
        pass
    return True  # Fallthrough


def _eval_date_clause(
    where_clause: str,
    col_name: str,
    order_value: str | None,
) -> bool:
    """Evaluate date/datetime column comparisons.

    Args:
        where_clause: Original WHERE clause.
        col_name: Column name being evaluated.
        order_value: The order's date string value.

    Returns:
        True if the clause matches.
    """
    import re
    from datetime import datetime

    date_match = re.search(
        rf"{col_name}\s*([><=]+)\s*['\"]?(\d{{4}}-\d{{2}}-\d{{2}})['\"]?",
        where_clause, re.IGNORECASE,
    )
    if not date_match:
        return True  # Fallthrough

    operator = date_match.group(1)
    target_date_str = date_match.group(2)
    try:
        target_date = datetime.fromisoformat(target_date_str)
        order_date_str = (order_value or "").split("T")[0]
        order_date = datetime.fromisoformat(order_date_str)

        if operator == ">=":
            return order_date >= target_date
        elif operator == ">":
            return order_date > target_date
        elif operator == "<=":
            return order_date <= target_date
        elif operator == "<":
            return order_date < target_date
        elif operator == "=":
            return order_date.date() == target_date.date()
    except ValueError:
        pass
    return True  # Fallthrough


def _order_matches_filter(order: ExternalOrder, where_clause: str) -> bool:
    """Check if a single order matches the WHERE clause.

    Uses data-driven dispatch: identifies the referenced column from the
    schema registry, gets the order value via getattr, and delegates to
    type-specific evaluator functions.

    Args:
        order: The order to check.
        where_clause: SQL WHERE clause to evaluate.

    Returns:
        True if order matches the filter.
    """
    # Handle compound AND/OR clauses
    op, sub_clauses = _split_compound_clause(where_clause)
    if op == "OR" and len(sub_clauses) > 1:
        return any(_order_matches_filter(order, sc) for sc in sub_clauses)
    if op == "AND" and len(sub_clauses) > 1:
        return all(_order_matches_filter(order, sc) for sc in sub_clauses)

    clause_lower = where_clause.lower().strip()

    # Find which column this clause references (longest match first)
    matched_col = None
    for col_name in _COLUMN_TYPES:
        if col_name in clause_lower:
            if matched_col is None or len(col_name) > len(matched_col):
                matched_col = col_name

    if matched_col is None:
        logger.warning(
            "FILTER FALLTHROUGH: No known column in '%s' for order %s. Including by default.",
            where_clause, order.order_id,
        )
        return True

    # Get the order's value for this column
    order_value = getattr(order, matched_col, None)
    col_type = _COLUMN_TYPES[matched_col]

    # Try IS NULL / IS NOT NULL first
    null_result = _eval_null_clause(clause_lower, matched_col, order_value)
    if null_result is not None:
        return null_result

    # Dispatch by column type
    if col_type in ("string",):
        return _eval_string_clause(where_clause, matched_col, order_value)
    elif col_type in ("numeric", "integer", "float", "number", "decimal"):
        return _eval_numeric_clause(where_clause, matched_col, order_value)
    elif col_type in ("datetime", "date", "timestamp"):
        return _eval_date_clause(where_clause, matched_col, order_value)

    logger.warning(
        "FILTER FALLTHROUGH: Unknown type '%s' for column '%s'. Including by default.",
        col_type, matched_col,
    )
    return True


class CommandProcessor:
    """Processes NL commands into ready-to-preview jobs.

    This service bridges the FastAPI command endpoint to the NL pipeline,
    handling the full flow from natural language command to job rows with
    cost estimates.

    Attributes:
        db_session_factory: Callable that returns a new database session.
        platform_state_manager: Reference to platform state manager for client access.
    """

    def __init__(
        self,
        db_session_factory: Callable[[], Session],
        platform_state_manager: Any = None,
    ) -> None:
        """Initialize CommandProcessor.

        Args:
            db_session_factory: Factory function that creates database sessions.
            platform_state_manager: Optional platform state manager instance.
                If not provided, will import the global instance.
        """
        self._db_session_factory = db_session_factory
        self._platform_state_manager = platform_state_manager

    def _get_platform_state_manager(self) -> Any:
        """Get the platform state manager, importing if necessary.

        Returns:
            The PlatformStateManager instance.
        """
        if self._platform_state_manager is None:
            from src.api.routes.platforms import _state_manager

            return _state_manager
        return self._platform_state_manager

    async def process(self, job_id: str, command: str) -> None:
        """Process a natural language command into job rows.

        This is the main entry point for command processing. It:
        1. Parses the intent from the command
        2. Generates a SQL filter from filter criteria
        3. Fetches matching orders from connected platforms
        4. Creates JobRows with cost estimates
        5. Updates the job with total row count

        Args:
            job_id: The UUID of the job to populate.
            command: The natural language shipping command.
        """
        db = self._db_session_factory()
        try:
            await self._process_internal(db, job_id, command)
        except Exception as e:
            logger.exception("Error processing command for job %s: %s", job_id, e)
            # Update job with error
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                job.error_code = "E-4001"
                job.error_message = str(e)
                db.commit()
        finally:
            db.close()

    async def _process_internal(
        self,
        db: Session,
        job_id: str,
        command: str,
    ) -> None:
        """Internal processing logic.

        Routes to local data source path or Shopify path based on
        what data source is currently connected.

        Args:
            db: Database session.
            job_id: The job UUID.
            command: The NL command.
        """
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.error("Job not found: %s", job_id)
            return

        # Check if a local data source is active
        ds_service = DataSourceService.get_instance()
        source_info = ds_service.get_source_info()

        if source_info is not None:
            logger.info(
                "Local data source active (%s, %d rows) — using local path",
                source_info.source_type,
                source_info.row_count,
            )
            await self._process_local_source(db, job, command, ds_service, source_info)
            return

        # Fall back to Shopify path
        await self._process_shopify_source(db, job, command)

    async def _process_local_source(
        self,
        db: Session,
        job: Any,
        command: str,
        ds_service: DataSourceService,
        source_info: Any,
    ) -> None:
        """Process command against a local data source (CSV/Excel/DB).

        Steps:
        1. Parse intent from NL command
        2. Build schema from source columns
        3. Generate SQL filter
        4. Fetch filtered rows from DuckDB
        5. Auto-map columns to UPS fields
        6. Create JobRows with mapped order_data
        7. Rate via BatchEngine.preview()

        Args:
            db: Database session.
            job: The Job ORM object.
            command: The NL command.
            ds_service: The DataSourceService instance.
            source_info: DataSourceInfo with schema and metadata.
        """
        job_id = job.id

        # Step 1: Parse intent
        logger.info("Parsing intent for job %s: %s", job_id, command[:50])
        try:
            intent = parse_intent(command)
            logger.info(
                "Parsed intent: action=%s, service=%s, filter=%s",
                intent.action,
                intent.service_code,
                intent.filter_criteria,
            )
        except IntentParseError as e:
            logger.warning("Intent parse error for job %s: %s", job_id, e.message)
            job.error_code = "E-4002"
            job.error_message = f"Could not understand command: {e.message}"
            if e.suggestions:
                job.error_message += f"\nTry: {', '.join(e.suggestions)}"
            db.commit()
            return

        # Step 2: Build dynamic schema from source columns
        # Get sample rows for context (helps LLM ground the filter)
        sample_rows = await ds_service.get_rows_by_filter(where_clause=None, limit=5)
        local_schema: list[ColumnInfo] = []
        for col in source_info.columns:
            # Map DuckDB types to ColumnInfo types
            col_type = _duckdb_type_to_column_type(col.type)
            # Get sample values from sample rows
            samples = [
                row.get(col.name)
                for row in sample_rows
                if row.get(col.name) is not None
            ][:3]
            local_schema.append(
                ColumnInfo(
                    name=col.name,
                    type=col_type,
                    nullable=col.nullable,
                    sample_values=samples if samples else None,
                )
            )

        # Step 3: Generate SQL filter if filter criteria present
        filter_result: SQLFilterResult | None = None
        if intent.filter_criteria and intent.filter_criteria.raw_expression:
            logger.info(
                "Generating filter for local source: %s",
                intent.filter_criteria.raw_expression,
            )
            try:
                filter_result = generate_filter(
                    intent.filter_criteria.raw_expression,
                    local_schema,
                )
                logger.info("Generated filter: %s", filter_result.where_clause)

                if filter_result.needs_clarification:
                    questions = filter_result.clarification_questions
                    job.error_code = "E-4003"
                    job.error_message = (
                        "Filter is ambiguous. Please clarify:\n"
                        + "\n".join(f"- {q}" for q in questions)
                    )
                    db.commit()
                    return

            except FilterGenerationError as e:
                logger.warning("Filter generation error for job %s: %s", job_id, e)
                job.error_code = "E-4004"
                job.error_message = f"Could not create filter: {e.message}"
                db.commit()
                return

        # Step 4: Fetch filtered rows from DuckDB
        where_clause = filter_result.where_clause if filter_result else None
        try:
            filtered_rows = await ds_service.get_rows_by_filter(
                where_clause=where_clause, limit=10000
            )
        except Exception as e:
            logger.error("Filter query failed for job %s: %s", job_id, e)
            job.error_code = "E-4004"
            job.error_message = f"Filter query failed: {e}"
            db.commit()
            return

        logger.info(
            "Filtered to %d rows (from %d total)",
            len(filtered_rows),
            source_info.row_count,
        )

        if not filtered_rows:
            job.error_code = "E-1002"
            job.error_message = (
                f"No rows match the filter criteria. "
                f"Filter: {where_clause or 'none'}"
            )
            db.commit()
            return

        # Step 5: Auto-map columns
        column_names = [col.name for col in source_info.columns]
        col_mapping = auto_map_columns(column_names)
        logger.info("Auto-mapped %d columns: %s", len(col_mapping), col_mapping)

        # Validate mapping has required fields
        mapping_errors = validate_mapping(col_mapping)
        if mapping_errors:
            logger.warning(
                "Column mapping validation warnings for job %s: %s",
                job_id,
                mapping_errors,
            )
            # Continue anyway — some fields may not be mappable but we'll
            # let the payload builder handle missing fields downstream

        # Step 6: Determine service code
        service_code = intent.service_code.value if intent.service_code else None

        # Step 7: Create JobRows with mapped order_data
        logger.info("Creating %d job rows for job %s", len(filtered_rows), job_id)

        for i, raw_row in enumerate(filtered_rows, start=1):
            # Apply column mapping to get canonical order_data
            order_data = apply_mapping(col_mapping, raw_row)

            # Handle service code: from intent or from row data
            if service_code:
                order_data["service_code"] = service_code
            elif "service_code" in order_data:
                # Translate service name to code (e.g., "Ground" → "03")
                order_data["service_code"] = translate_service_name(
                    str(order_data["service_code"])
                )
            else:
                order_data["service_code"] = "03"  # Default to Ground

            # Use row number from source if available
            row_number = raw_row.get("_row_number", i)

            # Compute checksum from raw row data (excluding _row_number)
            checksum_data = {
                k: v for k, v in raw_row.items() if k != "_row_number"
            }
            checksum_json = json.dumps(checksum_data, sort_keys=True, default=str)
            checksum = hashlib.sha256(checksum_json.encode("utf-8")).hexdigest()

            row = JobRow(
                job_id=job_id,
                row_number=int(row_number),
                row_checksum=checksum,
                status=RowStatus.pending.value,
                cost_cents=0,
                order_data=json.dumps(order_data, default=str),
            )
            db.add(row)

        # Step 8: Rate via UPS
        db.flush()
        await self._rate_job_rows(db, job_id, service_code or "03")

        # Step 9: Set total_rows and commit
        job.total_rows = len(filtered_rows)
        db.commit()

        logger.info(
            "Successfully processed local source command for job %s: %d rows created",
            job_id,
            len(filtered_rows),
        )

    async def _process_shopify_source(
        self,
        db: Session,
        job: Any,
        command: str,
    ) -> None:
        """Process command against Shopify (original path).

        Args:
            db: Database session.
            job: The Job ORM object.
            command: The NL command.
        """
        job_id = job.id

        # Step 1: Parse intent
        logger.info("Parsing intent for job %s: %s", job_id, command[:50])
        try:
            intent = parse_intent(command)
            logger.info(
                "Parsed intent: action=%s, service=%s, filter=%s",
                intent.action,
                intent.service_code,
                intent.filter_criteria,
            )
        except IntentParseError as e:
            logger.warning("Intent parse error for job %s: %s", job_id, e.message)
            job.error_code = "E-4002"
            job.error_message = f"Could not understand command: {e.message}"
            if e.suggestions:
                job.error_message += f"\nTry: {', '.join(e.suggestions)}"
            db.commit()
            return

        # Step 2: Generate SQL filter if filter criteria present
        filter_result: SQLFilterResult | None = None
        if intent.filter_criteria and intent.filter_criteria.raw_expression:
            logger.info(
                "Generating filter for: %s", intent.filter_criteria.raw_expression
            )
            try:
                filter_result = generate_filter(
                    intent.filter_criteria.raw_expression,
                    SHOPIFY_ORDER_SCHEMA,
                )
                logger.info("Generated filter: %s", filter_result.where_clause)

                # Check if clarification needed
                if filter_result.needs_clarification:
                    questions = filter_result.clarification_questions
                    job.error_code = "E-4003"
                    job.error_message = (
                        "Filter is ambiguous. Please clarify:\n"
                        + "\n".join(f"- {q}" for q in questions)
                    )
                    db.commit()
                    return

            except FilterGenerationError as e:
                logger.warning("Filter generation error for job %s: %s", job_id, e)
                job.error_code = "E-4004"
                job.error_message = f"Could not create filter: {e.message}"
                db.commit()
                return

        # Step 3: Fetch orders from connected platform
        state_manager = self._get_platform_state_manager()
        client = await state_manager.get_client("shopify")

        if client is None:
            logger.warning("Shopify not connected for job %s", job_id)
            job.error_code = "E-5002"
            job.error_message = (
                "No data source connected. Please import a CSV/Excel file "
                "or connect Shopify in Data Sources."
            )
            db.commit()
            return

        # Fetch unfulfilled orders by default
        logger.info("Fetching orders from Shopify for job %s", job_id)
        filters = OrderFilters(status="unfulfilled", limit=250)
        orders = await client.fetch_orders(filters)
        logger.info("Fetched %d orders from Shopify", len(orders))

        if not orders:
            job.error_code = "E-1001"
            job.error_message = "No unfulfilled orders found in Shopify."
            db.commit()
            return

        # Step 4: Apply filter to orders
        if filter_result:
            filtered_orders = apply_filter_to_orders(orders, filter_result)
            logger.info(
                "Filtered %d orders to %d matching orders",
                len(orders),
                len(filtered_orders),
            )
        else:
            filtered_orders = orders

        if not filtered_orders:
            job.error_code = "E-1002"
            job.error_message = (
                f"No orders match the filter criteria. "
                f"Filter: {filter_result.where_clause if filter_result else 'none'}"
            )
            db.commit()
            return

        # Step 5: Create JobRows (cost_cents=0 placeholder, rated below)
        logger.info("Creating %d job rows for job %s", len(filtered_orders), job_id)

        service_code = intent.service_code.value if intent.service_code else "03"

        for i, order in enumerate(filtered_orders, start=1):
            checksum = compute_order_checksum(order)

            order_data_dict = {
                col.name: getattr(order, col.name, None)
                for col in SHOPIFY_ORDER_SCHEMA
            }
            order_data_dict["service_code"] = service_code

            row = JobRow(
                job_id=job_id,
                row_number=i,
                row_checksum=checksum,
                status=RowStatus.pending.value,
                cost_cents=0,
                order_data=json.dumps(order_data_dict),
            )
            db.add(row)

        # Step 5b: Rate via UPS
        db.flush()
        await self._rate_job_rows(db, job_id, service_code)

        # Step 6: Set total_rows and commit (frontend sees preview is ready)
        job.total_rows = len(filtered_orders)
        db.commit()

        logger.info(
            "Successfully processed command for job %s: %d rows created",
            job_id,
            len(filtered_orders),
        )

    async def _rate_job_rows(
        self,
        db: Session,
        job_id: str,
        service_code: str,
    ) -> None:
        """Rate all rows in a job via UPS BatchEngine.preview().

        Args:
            db: Database session.
            job_id: The job UUID.
            service_code: UPS service code for rating.
        """
        try:
            ups_service = UPSService(
                base_url=os.environ.get("UPS_BASE_URL", "https://wwwcie.ups.com"),
                client_id=os.environ.get("UPS_CLIENT_ID", ""),
                client_secret=os.environ.get("UPS_CLIENT_SECRET", ""),
            )
            account_number = os.environ.get("UPS_ACCOUNT_NUMBER", "")
            engine = BatchEngine(
                ups_service=ups_service,
                db_session=db,
                account_number=account_number,
            )
            shipper = build_shipper_from_env()
            flushed_rows = (
                db.query(JobRow)
                .filter(JobRow.job_id == job_id)
                .order_by(JobRow.row_number)
                .all()
            )
            preview_result = await engine.preview(
                job_id, flushed_rows, shipper, service_code
            )

            # Map rated costs from preview result
            rated_costs = {
                pr["row_number"]: pr["estimated_cost_cents"]
                for pr in preview_result["preview_rows"]
            }
            # Compute average for rows beyond MAX_PREVIEW_ROWS
            if rated_costs:
                avg_cost = sum(rated_costs.values()) // len(rated_costs)
            else:
                avg_cost = 0

            for row in flushed_rows:
                row.cost_cents = rated_costs.get(row.row_number, avg_cost)

        except Exception as e:
            logger.warning(
                "UPS rating failed for job %s, preview will show $0 estimates: %s",
                job_id,
                e,
            )

__all__ = [
    "CommandProcessor",
    "SHOPIFY_ORDER_SCHEMA",
    "compute_order_checksum",
    "apply_filter_to_orders",
    "_duckdb_type_to_column_type",
]
