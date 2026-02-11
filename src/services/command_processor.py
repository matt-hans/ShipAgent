"""Command processor for NL shipping commands.

This module bridges the FastAPI command endpoint to the NL pipeline,
processing natural language commands into ready-to-preview jobs with
JobRows and cost estimates.

The CommandProcessor:
1. Parses intent via parse_intent()
2. Generates SQL filter via generate_filter()
3. Fetches orders from connected platforms matching the filter
4. Gets UPS rate quotes for each order
5. Creates JobRows with cost estimates
6. Updates Job total_rows count

Per CONTEXT.md Decision 1:
- LLM acts as Configuration Engine, not Data Pipe
- LLM interprets user intent and generates transformation rules
- Deterministic code executes those rules on actual shipping data
"""

import hashlib
import json
import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import Job, JobRow, RowStatus
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
]


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


def _order_matches_filter(order: ExternalOrder, where_clause: str) -> bool:
    """Check if a single order matches the WHERE clause.

    Supports compound AND/OR clauses by splitting into sub-clauses and
    evaluating each atomically. Also handles common single-column patterns:
    - String equality: column = 'value'
    - String LIKE: column LIKE '%value%'
    - Date comparisons: created_at >= 'YYYY-MM-DD'

    Supported columns:
    - order_id, order_number (exact match)
    - status (exact and LIKE)
    - created_at (date comparisons)
    - customer_name, customer_email (exact and LIKE)
    - ship_to_name, ship_to_company, ship_to_city, ship_to_state
    - ship_to_postal_code, ship_to_country

    Args:
        order: The order to check.
        where_clause: SQL WHERE clause to evaluate.

    Returns:
        True if order matches the filter.
    """
    import re
    from datetime import datetime, timedelta

    # Handle compound AND/OR clauses
    op, sub_clauses = _split_compound_clause(where_clause)
    if op == "OR" and len(sub_clauses) > 1:
        return any(_order_matches_filter(order, sc) for sc in sub_clauses)
    if op == "AND" and len(sub_clauses) > 1:
        return all(_order_matches_filter(order, sc) for sc in sub_clauses)

    clause_lower = where_clause.lower().strip()

    # Log the filter and order being evaluated for debugging
    logger.debug(
        "Evaluating filter '%s' for order %s (customer=%s, ship_to=%s)",
        where_clause,
        order.order_id,
        order.customer_name,
        order.ship_to_name,
    )

    # Try to evaluate common patterns

    # Pattern: order_id = 'XXX' or order_number = 'XXX'
    if "order_id" in clause_lower:
        match = re.search(
            r"order_id\s*=\s*['\"]?([^'\"]+)['\"]?",
            where_clause,
            re.IGNORECASE,
        )
        if match:
            target = match.group(1).strip()
            return order.order_id == target

    if "order_number" in clause_lower:
        match = re.search(
            r"order_number\s*=\s*['\"]?([^'\"]+)['\"]?",
            where_clause,
            re.IGNORECASE,
        )
        if match:
            target = match.group(1).strip()
            return order.order_number == target

    # Pattern: ship_to_state = 'XX'
    if "ship_to_state" in clause_lower:
        state_match = re.search(
            r"ship_to_state\s*=\s*['\"]?([A-Za-z]{2})['\"]?",
            where_clause,
            re.IGNORECASE,
        )
        if state_match:
            target_state = state_match.group(1).upper()
            return order.ship_to_state.upper() == target_state

    # Pattern: status LIKE '%unfulfilled%'
    if "status" in clause_lower and "like" in clause_lower:
        like_match = re.search(
            r"status\s+like\s+['\"]%?([^%'\"]+)%?['\"]",
            where_clause,
            re.IGNORECASE,
        )
        if like_match:
            target = like_match.group(1).lower()
            return target in order.status.lower()

    # Pattern: status = 'xxx/unfulfilled'
    if "status" in clause_lower and "=" in clause_lower:
        status_match = re.search(
            r"status\s*=\s*['\"]([^'\"]+)['\"]",
            where_clause,
            re.IGNORECASE,
        )
        if status_match:
            target_status = status_match.group(1).lower()
            return order.status.lower() == target_status

    # Pattern: ship_to_city = 'XXX'
    if "ship_to_city" in clause_lower:
        city_match = re.search(
            r"ship_to_city\s*=\s*['\"]([^'\"]+)['\"]",
            where_clause,
            re.IGNORECASE,
        )
        if city_match:
            target_city = city_match.group(1).lower()
            return order.ship_to_city.lower() == target_city

    # Pattern: customer_name = 'XXX' or customer_name LIKE '%XXX%'
    if "customer_name" in clause_lower:
        # Try exact match first
        name_match = re.search(
            r"customer_name\s*=\s*['\"]([^'\"]+)['\"]",
            where_clause,
            re.IGNORECASE,
        )
        if name_match:
            target_name = name_match.group(1).lower()
            return order.customer_name.lower() == target_name

        # Try LIKE pattern
        like_match = re.search(
            r"customer_name\s+like\s+['\"]%?([^%'\"]+)%?['\"]",
            where_clause,
            re.IGNORECASE,
        )
        if like_match:
            target_name = like_match.group(1).lower()
            return target_name in order.customer_name.lower()

    # Pattern: ship_to_name = 'XXX' or ship_to_name LIKE '%XXX%'
    if "ship_to_name" in clause_lower:
        # Try exact match first
        name_match = re.search(
            r"ship_to_name\s*=\s*['\"]([^'\"]+)['\"]",
            where_clause,
            re.IGNORECASE,
        )
        if name_match:
            target_name = name_match.group(1).lower()
            return order.ship_to_name.lower() == target_name

        # Try LIKE pattern
        like_match = re.search(
            r"ship_to_name\s+like\s+['\"]%?([^%'\"]+)%?['\"]",
            where_clause,
            re.IGNORECASE,
        )
        if like_match:
            target_name = like_match.group(1).lower()
            return target_name in order.ship_to_name.lower()

    # Pattern: ship_to_company = 'XXX' or ship_to_company LIKE '%XXX%'
    if "ship_to_company" in clause_lower:
        # Try exact match first
        match = re.search(
            r"ship_to_company\s*=\s*['\"]([^'\"]+)['\"]",
            where_clause,
            re.IGNORECASE,
        )
        if match:
            target = match.group(1).lower()
            company = order.ship_to_company or ""
            return company.lower() == target

        # Try LIKE pattern
        like_match = re.search(
            r"ship_to_company\s+like\s+['\"]%?([^%'\"]+)%?['\"]",
            where_clause,
            re.IGNORECASE,
        )
        if like_match:
            target = like_match.group(1).lower()
            company = order.ship_to_company or ""
            return target in company.lower()

    # Pattern: customer_email = 'XXX' or customer_email LIKE '%XXX%'
    if "customer_email" in clause_lower:
        # Try exact match first
        match = re.search(
            r"customer_email\s*=\s*['\"]([^'\"]+)['\"]",
            where_clause,
            re.IGNORECASE,
        )
        if match:
            target = match.group(1).lower()
            email = order.customer_email or ""
            return email.lower() == target

        # Try LIKE pattern
        like_match = re.search(
            r"customer_email\s+like\s+['\"]%?([^%'\"]+)%?['\"]",
            where_clause,
            re.IGNORECASE,
        )
        if like_match:
            target = like_match.group(1).lower()
            email = order.customer_email or ""
            return target in email.lower()

    # Pattern: ship_to_postal_code = 'XXXXX'
    if "ship_to_postal_code" in clause_lower:
        match = re.search(
            r"ship_to_postal_code\s*=\s*['\"]?([^'\"]+)['\"]?",
            where_clause,
            re.IGNORECASE,
        )
        if match:
            target = match.group(1).strip()
            return order.ship_to_postal_code == target

    # Pattern: ship_to_country = 'XX'
    if "ship_to_country" in clause_lower:
        match = re.search(
            r"ship_to_country\s*=\s*['\"]?([A-Za-z]{2})['\"]?",
            where_clause,
            re.IGNORECASE,
        )
        if match:
            target = match.group(1).upper()
            return order.ship_to_country.upper() == target

    # Pattern: ship_to_address1 = 'XXX' or ship_to_address1 LIKE '%XXX%'
    if "ship_to_address1" in clause_lower:
        # Try exact match first
        match = re.search(
            r"ship_to_address1\s*=\s*['\"]([^'\"]+)['\"]",
            where_clause,
            re.IGNORECASE,
        )
        if match:
            target = match.group(1).lower()
            return order.ship_to_address1.lower() == target

        # Try LIKE pattern
        like_match = re.search(
            r"ship_to_address1\s+like\s+['\"]%?([^%'\"]+)%?['\"]",
            where_clause,
            re.IGNORECASE,
        )
        if like_match:
            target = like_match.group(1).lower()
            return target in order.ship_to_address1.lower()

    # Pattern: ship_to_address2 = 'XXX' or ship_to_address2 LIKE '%XXX%'
    if "ship_to_address2" in clause_lower:
        addr2 = order.ship_to_address2 or ""
        # Try exact match first
        match = re.search(
            r"ship_to_address2\s*=\s*['\"]([^'\"]+)['\"]",
            where_clause,
            re.IGNORECASE,
        )
        if match:
            target = match.group(1).lower()
            return addr2.lower() == target

        # Try LIKE pattern
        like_match = re.search(
            r"ship_to_address2\s+like\s+['\"]%?([^%'\"]+)%?['\"]",
            where_clause,
            re.IGNORECASE,
        )
        if like_match:
            target = like_match.group(1).lower()
            return target in addr2.lower()

        # Handle NULL check
        if "is null" in clause_lower:
            return addr2 == "" or addr2 is None
        if "is not null" in clause_lower:
            return addr2 != "" and addr2 is not None

    # Pattern: ship_to_phone = 'XXX' or ship_to_phone LIKE '%XXX%'
    if "ship_to_phone" in clause_lower:
        phone = order.ship_to_phone or ""
        # Try exact match first
        match = re.search(
            r"ship_to_phone\s*=\s*['\"]([^'\"]+)['\"]",
            where_clause,
            re.IGNORECASE,
        )
        if match:
            target = match.group(1)
            # Normalize phone numbers for comparison (remove non-digits)
            target_digits = re.sub(r"\D", "", target)
            phone_digits = re.sub(r"\D", "", phone)
            return phone_digits == target_digits or phone == target

        # Try LIKE pattern
        like_match = re.search(
            r"ship_to_phone\s+like\s+['\"]%?([^%'\"]+)%?['\"]",
            where_clause,
            re.IGNORECASE,
        )
        if like_match:
            target = like_match.group(1)
            target_digits = re.sub(r"\D", "", target)
            phone_digits = re.sub(r"\D", "", phone)
            return target_digits in phone_digits or target in phone

    # Pattern: created_at date comparisons
    if "created_at" in clause_lower:
        # Parse date from filter
        date_match = re.search(
            r"created_at\s*([><=]+)\s*['\"]?(\d{4}-\d{2}-\d{2})['\"]?",
            where_clause,
            re.IGNORECASE,
        )
        if date_match:
            operator = date_match.group(1)
            target_date_str = date_match.group(2)
            try:
                target_date = datetime.fromisoformat(target_date_str)
                # Parse order date (handle ISO format with timezone)
                order_date_str = order.created_at.split("T")[0]
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
                pass  # Fall through to default

    # Default: if we can't parse the filter, log detailed info
    # This indicates a bug - we should handle all filter patterns
    logger.warning(
        "FILTER FALLTHROUGH: Could not evaluate filter '%s' for order %s "
        "(customer_name='%s', ship_to_name='%s'). Including by default. "
        "This indicates a missing filter pattern handler!",
        where_clause,
        order.order_id,
        order.customer_name,
        order.ship_to_name,
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

        Args:
            db: Database session.
            job_id: The job UUID.
            command: The NL command.
        """
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.error("Job not found: %s", job_id)
            return

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
                "Shopify not connected. Please connect Shopify first in Data Sources."
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

        # Step 5: Create JobRows with cost estimates
        logger.info("Creating %d job rows for job %s", len(filtered_orders), job_id)

        # Get service code from intent for cost estimation
        service_code = intent.service_code.value if intent.service_code else "03"

        for i, order in enumerate(filtered_orders, start=1):
            # Compute checksum for data integrity
            checksum = compute_order_checksum(order)

            # Estimate cost (in cents) - simplified for now
            # In production, this would call UPS rating API
            estimated_cost_cents = self._estimate_shipping_cost(order, service_code)

            # Serialize order data for preview (exclude raw_data to save space)
            order_data_dict = {
                "order_id": order.order_id,
                "order_number": order.order_number,
                "customer_name": order.customer_name,
                "customer_email": order.customer_email,
                "ship_to_name": order.ship_to_name,
                "ship_to_company": order.ship_to_company,
                "ship_to_address1": order.ship_to_address1,
                "ship_to_address2": order.ship_to_address2,
                "ship_to_city": order.ship_to_city,
                "ship_to_state": order.ship_to_state,
                "ship_to_postal_code": order.ship_to_postal_code,
                "ship_to_country": order.ship_to_country,
                "ship_to_phone": order.ship_to_phone,
                "service_code": service_code,
            }

            # Store order data in row for later use
            row = JobRow(
                job_id=job_id,
                row_number=i,
                row_checksum=checksum,
                status=RowStatus.pending.value,
                cost_cents=estimated_cost_cents,
                order_data=json.dumps(order_data_dict),
            )
            db.add(row)

        # Step 6: Update job with total rows
        job.total_rows = len(filtered_orders)
        db.commit()

        logger.info(
            "Successfully processed command for job %s: %d rows created",
            job_id,
            len(filtered_orders),
        )

    def _estimate_shipping_cost(
        self,
        order: ExternalOrder,
        service_code: str,
    ) -> int:
        """Estimate shipping cost for an order.

        This is a placeholder that provides reasonable estimates.
        In production, this would call the UPS rating API.

        Args:
            order: The order to estimate cost for.
            service_code: UPS service code (03=Ground, 01=Next Day, etc.).

        Returns:
            Estimated cost in cents.
        """
        # Base costs by service (simplified)
        base_costs = {
            "03": 899,  # Ground: $8.99 base
            "01": 2499,  # Next Day Air: $24.99 base
            "02": 1799,  # 2nd Day Air: $17.99 base
            "12": 999,  # 3 Day Select: $9.99 base
            "13": 699,  # Ground Saver: $6.99 base
        }

        base_cost = base_costs.get(service_code, 899)

        # Adjust for distance (very simplified - west coast vs east coast)
        west_coast_states = {"CA", "OR", "WA", "NV", "AZ"}
        east_coast_states = {"NY", "NJ", "MA", "PA", "FL", "GA", "NC", "VA"}

        state = order.ship_to_state.upper()
        if state in west_coast_states:
            # Assuming shipping from CA, west coast is cheaper
            distance_multiplier = 1.0
        elif state in east_coast_states:
            distance_multiplier = 1.3
        else:
            distance_multiplier = 1.15

        estimated_cost = int(base_cost * distance_multiplier)

        return estimated_cost


__all__ = [
    "CommandProcessor",
    "SHOPIFY_ORDER_SCHEMA",
    "compute_order_checksum",
    "apply_filter_to_orders",
]
