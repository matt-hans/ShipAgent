"""Exact private canonical framing and bounds, with no source authority."""

import hashlib
import importlib
import importlib.util
from dataclasses import replace

import pytest

from src.services.source_ingress.csv_snapshot import (
    CsvSnapshotError,
    parse_csv_snapshot,
)

RAW = b' Zip ,Note,Formula,Empty\n00123,"line1\n\xe9\x9b\xaa",=2+2,\n'
CANONICAL = (
    b"synthetic_csv_v1"
    b"\x00\x00\x00\x04"
    b"\x00\x00\x00\x05 Zip "
    b"\x00\x00\x00\x04Note"
    b"\x00\x00\x00\x07Formula"
    b"\x00\x00\x00\x05Empty"
    b"\x00\x00\x00\x04"
    b"\x00\x00\x00\x0500123"
    b"\x00\x00\x00\x09line1\n\xe9\x9b\xaa"
    b"\x00\x00\x00\x04=2+2"
    b"\x00\x00\x00\x00"
)


def implementation():
    name = "src.services.source_ingress.snapshot_codec"
    assert importlib.util.find_spec(name) is not None, (
        "bounded snapshot codec is absent"
    )
    return importlib.import_module(name)


def test_fixed_canonical_vector_preserves_exact_private_strings_and_identity():
    codec = implementation()
    snapshot = parse_csv_snapshot(
        RAW,
        content_length=len(RAW),
        content_sha256=hashlib.sha256(RAW).hexdigest(),
        media_type="text/csv",
    )
    assert codec.encode_snapshot(snapshot) == CANONICAL
    assert hashlib.sha256(CANONICAL).hexdigest() == snapshot.snapshot_identity
    result = codec.decode_snapshot(
        CANONICAL,
        raw_content_sha256=snapshot.raw_content_sha256,
        expected_identity=snapshot.snapshot_identity,
        row_count=1,
        column_count=4,
    )
    assert result == snapshot
    assert result.headers == (" Zip ", "Note", "Formula", "Empty")
    assert result.rows == (("00123", "line1\n雪", "=2+2", ""),)
    assert result.column_references == (
        "column_0001",
        "column_0002",
        "column_0003",
        "column_0004",
    )
    assert "00123" not in repr(result) and "Formula" not in repr(result)


def parsed():
    return parse_csv_snapshot(
        RAW,
        content_length=len(RAW),
        content_sha256=hashlib.sha256(RAW).hexdigest(),
        media_type="text/csv",
    )


def decode(content, **changes):
    values = {
        "raw_content_sha256": hashlib.sha256(RAW).hexdigest(),
        "expected_identity": hashlib.sha256(content).hexdigest(),
        "row_count": 1,
        "column_count": 4,
    }
    values.update(changes)
    return implementation().decode_snapshot(content, **values)


def framed(records):
    result = b"synthetic_csv_v1"
    for record in records:
        result += len(record).to_bytes(4, "big")
        for value in record:
            field = value.encode("utf-8")
            result += len(field).to_bytes(4, "big") + field
    return result


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"different_profile" + CANONICAL[16:],
        CANONICAL + b"x",
        CANONICAL[:-1],
        CANONICAL[:25],
        CANONICAL[:50],
        CANONICAL[:-8] + b"\xff" + CANONICAL[-7:],
        b"synthetic_csv_v1" + (65).to_bytes(4, "big"),
        CANONICAL + b"x" * (2 * 1024 * 1024),
    ],
)
def test_decoder_rejects_incomplete_trailing_oversized_or_invalid_framing(content):
    with pytest.raises(CsvSnapshotError) as error:
        decode(content)
    assert error.value.__context__ is None
    assert "line1" not in str(error.value)


@pytest.mark.parametrize(
    "changes",
    [
        {"row_count": 0},
        {"row_count": 2},
        {"row_count": 10001},
        {"column_count": 65},
        {"column_count": 3},
        {"row_count": True},
        {"column_count": False},
        {"expected_identity": "0" * 64},
        {"expected_identity": "PRIVATE_HASH_CANARY"},
        {"raw_content_sha256": "PRIVATE_RAW_CANARY"},
    ],
)
def test_decoder_counts_and_identity_are_exact_bounded_metadata(changes):
    with pytest.raises(CsvSnapshotError) as error:
        decode(CANONICAL, **changes)
    assert "PRIVATE_" not in str(error.value)


@pytest.mark.parametrize(
    "headers,rows",
    [
        (("A", " a "), (("x", "y"),)),
        ((" ",), (("x",),)),
        (("A",), ()),
        (("A",), (("x", "y"),)),
        (("A\x00",), (("x",),)),
        (("A",), (("PRIVATE_CELL\x00",),)),
        (("A",), (("x" * 16385,),)),
    ],
)
def test_decoder_rejects_values_outside_existing_parser_profile(headers, rows):
    content = framed((headers, *rows))
    with pytest.raises(CsvSnapshotError) as error:
        decode(content, row_count=len(rows), column_count=len(headers))
    assert "PRIVATE_CELL" not in str(error.value)


@pytest.mark.parametrize(
    "changes",
    [
        {"headers": ["A"]},
        {"rows": [["x"]]},
        {"headers": ("A", " a ")},
        {"rows": ()},
        {"rows": (("x",),)},
        {"rows": ((1, "y", "z", "q"),)},
        {"rows": (("\ud800", "y", "z", "q"),)},
        {"rows": (("PRIVATE_CELL\x00", "y", "z", "q"),)},
        {"rows": (("x" * 16385, "y", "z", "q"),)},
        {"column_references": ("PRIVATE_COLUMN",) * 4},
        {"raw_content_sha256": "private"},
        {"snapshot_identity": "0" * 64},
    ],
)
def test_encoder_validates_snapshot_shape_and_private_identity(changes):
    with pytest.raises(CsvSnapshotError) as error:
        implementation().encode_snapshot(replace(parsed(), **changes))
    assert error.value.__context__ is None
    assert "PRIVATE_" not in str(error.value)


def test_encoder_caps_total_bytes_even_when_individual_fields_are_small():
    snapshot = replace(
        parsed(),
        headers=tuple(f"h{i}" for i in range(64)),
        rows=(tuple("" for _ in range(64)),) * 10000,
        column_references=tuple(f"column_{i:04d}" for i in range(1, 65)),
    )
    with pytest.raises(CsvSnapshotError) as error:
        implementation().encode_snapshot(snapshot)
    assert error.value.code == "source_limit_exceeded"


@pytest.mark.parametrize("width,length", [(2**32 - 1, 0), (1, 2**32 - 1), (1, 16385)])
def test_uint32_framing_is_bounded_before_loop_or_allocation(width, length):
    body = b"synthetic_csv_v1" + width.to_bytes(4, "big") + length.to_bytes(4, "big")
    with pytest.raises(CsvSnapshotError):
        decode(body, column_count=1)


@pytest.mark.parametrize(
    "value", [None, "private", bytearray(CANONICAL), memoryview(CANONICAL)]
)
def test_decoder_accepts_only_exact_bytes(value):
    with pytest.raises(CsvSnapshotError):
        implementation().decode_snapshot(
            value,
            raw_content_sha256="0" * 64,
            expected_identity="0" * 64,
            row_count=1,
            column_count=4,
        )


def test_unicode_field_byte_boundary_preserves_exact_values():
    for value in ("x" * 16384, "雪" * 5461 + "x", "=formula", " 00123 "):
        body = framed((("Header",), (value,)))
        snapshot = decode(body, row_count=1, column_count=1)
        assert snapshot.rows == ((value,),)
        assert implementation().encode_snapshot(snapshot) == body
    with pytest.raises(CsvSnapshotError):
        decode(framed((("Header",), ("雪" * 5462,))), column_count=1)


def test_column_references_are_exact_strings_without_dynamic_equality():
    class Reference(str):
        pass

    forged = replace(
        parsed(),
        column_references=tuple(
            Reference(value) for value in parsed().column_references
        ),
    )
    with pytest.raises(CsvSnapshotError):
        implementation().encode_snapshot(forged)
