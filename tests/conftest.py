"""Root-level pytest fixtures for all tests.

Provides shared fixtures for integration testing including:
- Database fixtures (file-based SQLite)
- MCP client fixtures
- Shopify store fixtures
- Common test data generators
"""

import csv
import os
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base

# Define PROJECT_ROOT locally to avoid importing from orchestrator.agent
# which has heavy dependencies (claude_agent_sdk) not needed for basic tests
PROJECT_ROOT = Path(__file__).parent.parent


# ============================================================================
# Pytest Markers
# ============================================================================


def pytest_configure(config):
    """Register custom markers and set required env vars."""
    config.addinivalue_line(
        "markers", "integration: marks tests requiring external services"
    )
    config.addinivalue_line(
        "markers", "shopify: marks tests requiring Shopify credentials"
    )
    config.addinivalue_line(
        "markers", "slow: marks tests that take a long time to run"
    )

    # Set UPS_MCP_SPECS_DIR so ups_mcp module can find OpenAPI spec YAMLs
    # when imported (even when ToolManager is mocked, the module import
    # still needs to load the registry).
    if not os.environ.get("UPS_MCP_SPECS_DIR"):
        specs_dir = str(PROJECT_ROOT / "src" / "mcp" / "ups" / "specs")
        if Path(specs_dir).is_dir():
            os.environ["UPS_MCP_SPECS_DIR"] = specs_dir


# ============================================================================
# Skip Conditions
# ============================================================================

requires_anthropic_key = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set"
)

requires_shopify_credentials = pytest.mark.skipif(
    not (os.environ.get("SHOPIFY_ACCESS_TOKEN") and os.environ.get("SHOPIFY_STORE_DOMAIN")),
    reason="Shopify credentials not set"
)


# ============================================================================
# Database Fixtures
# ============================================================================


@pytest.fixture
def file_based_db() -> Generator[str, None, None]:
    """Create a file-based SQLite database for integration tests.

    Unlike in-memory databases, this persists across connections
    and can be used for multi-process testing.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)

    yield path

    os.unlink(path)


@pytest.fixture
def integration_db_session(file_based_db: str):
    """Create database session for integration tests."""
    engine = create_engine(f"sqlite:///{file_based_db}")
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


# ============================================================================
# Test Data Fixtures
# ============================================================================


@pytest.fixture
def sample_shipping_csv() -> Generator[str, None, None]:
    """Create a sample CSV file with shipping data."""
    fd, path = tempfile.mkstemp(suffix=".csv")

    with os.fdopen(fd, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            "order_id", "recipient_name", "address", "city", "state", "zip",
            "country", "weight_lbs", "service_type"
        ])
        writer.writeheader()

        test_orders = [
            {"order_id": "1001", "recipient_name": "Alice Johnson", "address": "123 Main St",
             "city": "Los Angeles", "state": "CA", "zip": "90001", "country": "US",
             "weight_lbs": "2.5", "service_type": "Ground"},
            {"order_id": "1002", "recipient_name": "Bob Smith", "address": "456 Oak Ave",
             "city": "San Francisco", "state": "CA", "zip": "94102", "country": "US",
             "weight_lbs": "1.2", "service_type": "Ground"},
            {"order_id": "1003", "recipient_name": "Carol White", "address": "789 Pine Rd",
             "city": "San Diego", "state": "CA", "zip": "92101", "country": "US",
             "weight_lbs": "5.0", "service_type": "Next Day Air"},
            {"order_id": "1004", "recipient_name": "David Brown", "address": "321 Elm St",
             "city": "Portland", "state": "OR", "zip": "97201", "country": "US",
             "weight_lbs": "3.3", "service_type": "Ground"},
            {"order_id": "1005", "recipient_name": "Eve Wilson", "address": "654 Maple Dr",
             "city": "Seattle", "state": "WA", "zip": "98101", "country": "US",
             "weight_lbs": "0.8", "service_type": "2nd Day Air"},
        ]

        for order in test_orders:
            writer.writerow(order)

    yield path
    os.unlink(path)


@pytest.fixture
def large_shipping_csv() -> Generator[str, None, None]:
    """Create a large CSV file with 1000 rows for scale testing."""
    fd, path = tempfile.mkstemp(suffix=".csv")

    with os.fdopen(fd, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            "order_id", "recipient_name", "address", "city", "state", "zip",
            "country", "weight_lbs", "service_type"
        ])
        writer.writeheader()

        states = ["CA", "OR", "WA", "NV", "AZ"]
        cities = {
            "CA": [("Los Angeles", "90001"), ("San Francisco", "94102")],
            "OR": [("Portland", "97201")],
            "WA": [("Seattle", "98101")],
            "NV": [("Las Vegas", "89101")],
            "AZ": [("Phoenix", "85001")],
        }
        services = ["Ground", "2nd Day Air", "Next Day Air"]

        for i in range(1000):
            state = states[i % len(states)]
            city, zip_code = cities[state][i % len(cities[state])]
            writer.writerow({
                "order_id": str(10000 + i),
                "recipient_name": f"Customer {i}",
                "address": f"{i} Test Street",
                "city": city,
                "state": state,
                "zip": zip_code,
                "country": "US",
                "weight_lbs": str(round(1.0 + (i % 10) * 0.5, 1)),
                "service_type": services[i % len(services)],
            })

    yield path
    os.unlink(path)


# ============================================================================
# MCP Fixtures
# ============================================================================


@pytest.fixture
def data_mcp_config() -> dict:
    """Get Data MCP configuration for testing."""
    from src.orchestrator.agent.config import get_data_mcp_config
    return get_data_mcp_config()


@pytest.fixture
def shopify_mcp_config() -> dict:
    """Get External Sources MCP configuration for testing."""
    from src.orchestrator.agent.config import get_external_sources_mcp_config
    return get_external_sources_mcp_config()
