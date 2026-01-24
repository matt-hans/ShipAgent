"""Test checksum functionality."""

import pytest

from src.mcp.data_source.utils import compute_row_checksum


def test_checksum_deterministic():
    """Same data produces same checksum."""
    data1 = {"a": 1, "b": 2, "c": "hello"}
    data2 = {"a": 1, "b": 2, "c": "hello"}

    assert compute_row_checksum(data1) == compute_row_checksum(data2)


def test_checksum_order_independent():
    """Key order doesn't affect checksum."""
    data1 = {"a": 1, "b": 2, "c": 3}
    data2 = {"c": 3, "a": 1, "b": 2}

    assert compute_row_checksum(data1) == compute_row_checksum(data2)


def test_checksum_different_data():
    """Different data produces different checksum."""
    data1 = {"a": 1, "b": 2}
    data2 = {"a": 1, "b": 3}

    assert compute_row_checksum(data1) != compute_row_checksum(data2)


def test_checksum_format():
    """Checksum is 64-char hex string (SHA-256)."""
    data = {"test": "value"}
    checksum = compute_row_checksum(data)

    assert len(checksum) == 64
    assert all(c in "0123456789abcdef" for c in checksum)
