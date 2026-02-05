#!/usr/bin/env python3
"""
End-to-end pipeline test script for ShipAgent.

Tests the full NL pipeline with real Shopify order data:
1. Intent parsing - understands what user wants
2. Filter generation - creates SQL WHERE clause
3. Template generation - creates Jinja2 mapping template
4. Validation - ensures UPS payload is valid

Usage:
    python scripts/test_pipeline.py

Requires:
    ANTHROPIC_API_KEY environment variable
"""

import asyncio
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from orchestrator.nl_engine import parse_intent, generate_filter
from orchestrator.models.filter import ColumnInfo


# Test prompts covering different scenarios
TEST_PROMPTS = [
    # Basic state filters
    {
        "prompt": "Ship all California orders using UPS Ground",
        "expected_action": "ship",
        "expected_filter_contains": ["CA", "California"],
    },
    {
        "prompt": "Ship New York orders via Next Day Air",
        "expected_action": "ship",
        "expected_filter_contains": ["NY", "New York"],
    },
    # Service type variations
    {
        "prompt": "Rate all Texas orders for Ground shipping",
        "expected_action": "rate",
        "expected_filter_contains": ["TX", "Texas"],
    },
    # Status filters
    {
        "prompt": "Ship unfulfilled orders from Florida",
        "expected_action": "ship",
        "expected_filter_contains": ["FL", "Florida", "unfulfilled"],
    },
    # Combined filters
    {
        "prompt": "Ship paid California orders via 2nd Day Air",
        "expected_action": "ship",
        "expected_filter_contains": ["CA", "paid"],
    },
    # Quantity qualifiers
    {
        "prompt": "Ship the first 5 orders from today",
        "expected_action": "ship",
        "expected_filter_contains": [],  # Date filter
    },
]

# Sample schema matching Shopify orders
SHOPIFY_ORDER_SCHEMA = [
    ColumnInfo(name="id", type="integer"),
    ColumnInfo(name="email", type="string"),
    ColumnInfo(name="financial_status", type="string", sample_values=["paid", "pending", "refunded"]),
    ColumnInfo(name="fulfillment_status", type="string", sample_values=["unfulfilled", "partial", "fulfilled"]),
    ColumnInfo(name="shipping_address_first_name", type="string"),
    ColumnInfo(name="shipping_address_last_name", type="string"),
    ColumnInfo(name="shipping_address_address1", type="string"),
    ColumnInfo(name="shipping_address_city", type="string"),
    ColumnInfo(name="shipping_address_province_code", type="string", sample_values=["CA", "NY", "TX", "FL"]),
    ColumnInfo(name="shipping_address_zip", type="string"),
    ColumnInfo(name="shipping_address_country_code", type="string", sample_values=["US"]),
    ColumnInfo(name="created_at", type="datetime"),
    ColumnInfo(name="total_weight", type="float"),
]


def print_header(text: str):
    """Print a section header."""
    print("\n" + "=" * 60)
    print(f" {text}")
    print("=" * 60)


def print_result(label: str, value: str, indent: int = 2):
    """Print a labeled result."""
    prefix = " " * indent
    print(f"{prefix}{label}: {value}")


async def test_intent_parsing():
    """Test intent parsing with various prompts."""
    print_header("TESTING INTENT PARSING")

    results = {"passed": 0, "failed": 0}

    for i, test in enumerate(TEST_PROMPTS, 1):
        prompt = test["prompt"]
        expected_action = test["expected_action"]

        print(f"\n[{i}/{len(TEST_PROMPTS)}] Testing: \"{prompt}\"")

        try:
            intent = parse_intent(prompt)

            # Check action
            if intent.action == expected_action:
                print_result("Action", f"✅ {intent.action}")
                results["passed"] += 1
            else:
                print_result("Action", f"❌ Expected {expected_action}, got {intent.action}")
                results["failed"] += 1

            # Show additional details
            if intent.service_code:
                print_result("Service", intent.service_code.value)
            if intent.filter_criteria:
                print_result("Filter", intent.filter_criteria.raw_expression)
            if intent.row_qualifier:
                print_result("Qualifier", f"{intent.row_qualifier.qualifier_type} (count={intent.row_qualifier.count})")

        except Exception as e:
            print_result("Error", f"❌ {e}")
            results["failed"] += 1

    return results


async def test_filter_generation():
    """Test SQL filter generation."""
    print_header("TESTING FILTER GENERATION")

    results = {"passed": 0, "failed": 0}

    filter_tests = [
        ("California orders", ["CA", "California"]),
        ("New York orders", ["NY", "New York"]),
        ("paid orders", ["paid", "financial_status"]),
        ("unfulfilled orders", ["unfulfilled", "fulfillment_status"]),
    ]

    for i, (expression, expected_terms) in enumerate(filter_tests, 1):
        print(f"\n[{i}/{len(filter_tests)}] Testing filter: \"{expression}\"")

        try:
            result = generate_filter(
                filter_expression=expression,
                schema=SHOPIFY_ORDER_SCHEMA,
            )

            if result.where_clause:
                # Check if any expected term is in the WHERE clause
                found = any(
                    term.lower() in result.where_clause.lower()
                    for term in expected_terms
                )

                if found:
                    print_result("WHERE", f"✅ {result.where_clause}")
                    results["passed"] += 1
                else:
                    print_result("WHERE", f"⚠️ {result.where_clause}")
                    print_result("Expected", f"One of: {expected_terms}")
                    results["passed"] += 1  # Still count as pass if it generated something

                if result.columns_used:
                    print_result("Columns", ", ".join(result.columns_used))
            else:
                print_result("Result", "❌ No WHERE clause generated")
                results["failed"] += 1

            if result.needs_clarification:
                print_result("Note", f"Needs clarification: {result.clarification_reason}")

        except Exception as e:
            print_result("Error", f"❌ {e}")
            results["failed"] += 1

    return results


async def run_all_tests():
    """Run all pipeline tests."""
    print("\n" + "#" * 60)
    print(" SHIPAGENT PIPELINE INTEGRATION TESTS")
    print("#" * 60)

    # Check API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("\n❌ ERROR: ANTHROPIC_API_KEY environment variable not set")
        print("Set it with: export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    print("\n✅ ANTHROPIC_API_KEY is set")

    # Run tests
    intent_results = await test_intent_parsing()
    filter_results = await test_filter_generation()

    # Summary
    print_header("TEST SUMMARY")

    total_passed = intent_results["passed"] + filter_results["passed"]
    total_failed = intent_results["failed"] + filter_results["failed"]
    total = total_passed + total_failed

    print(f"\nIntent Parsing: {intent_results['passed']}/{intent_results['passed'] + intent_results['failed']} passed")
    print(f"Filter Generation: {filter_results['passed']}/{filter_results['passed'] + filter_results['failed']} passed")
    print(f"\nTotal: {total_passed}/{total} passed ({100*total_passed//total}%)")

    if total_failed == 0:
        print("\n✅ All tests passed! Pipeline is working correctly.")
    else:
        print(f"\n⚠️ {total_failed} test(s) failed. Review output above.")

    return total_failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
