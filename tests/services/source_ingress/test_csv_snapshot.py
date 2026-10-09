"""Behavior of the private synthetic CSV substrate, without ingress authority."""

import hashlib
import importlib

import pytest


def api():
    try:
        return importlib.import_module("src.services.source_ingress.csv_snapshot")
    except ModuleNotFoundError as error:
        if error.name in {
            "src.services.source_ingress",
            "src.services.source_ingress.csv_snapshot",
        }:
            pytest.fail("CSV snapshot substrate is not implemented", pytrace=False)
        raise


def parse(data: bytes, **changes):
    options = {
        "content_length": len(data),
        "content_sha256": hashlib.sha256(data).hexdigest(),
        "media_type": "text/csv",
    }
    options.update(changes)
    return api().parse_csv_snapshot(data, **options)


def test_private_snapshot_preserves_exact_strings_and_fixed_column_identity():
    data = (
        "\ufeffpostal_code,recipient_name,notes\r\n"
        '00123,"  Synthetïc 名  ","=HYPERLINK(""https://example.invalid"",'
        '""inert"")\r\nsecond line"\r\n'
    ).encode()
    snapshot = parse(data)
    assert snapshot.headers == ("postal_code", "recipient_name", "notes")
    assert snapshot.column_references == ("column_0001", "column_0002", "column_0003")
    assert snapshot.rows == (
        (
            "00123",
            "  Synthetïc 名  ",
            '=HYPERLINK("https://example.invalid","inert")\r\nsecond line',
        ),
    )
    assert snapshot.row_count == 1
    assert snapshot.column_count == 3


def test_private_identity_is_content_based_but_never_mutates_prior_snapshot():
    from dataclasses import FrozenInstanceError

    first = parse(b"postal_code,notes\n00123,plain\n")
    same = parse(b'\xef\xbb\xbf"postal_code",notes\r\n"00123",plain\r\n')
    changed = parse(b"postal_code,notes\n00124,plain\n")
    assert (
        first.raw_content_sha256
        == hashlib.sha256(b"postal_code,notes\n00123,plain\n").hexdigest()
    )
    assert first.raw_content_sha256 != same.raw_content_sha256
    assert first.snapshot_identity == same.snapshot_identity
    assert first.snapshot_identity != changed.snapshot_identity
    assert first.rows == (("00123", "plain"),)
    with pytest.raises(FrozenInstanceError):
        first.headers = ("changed",)
    with pytest.raises(TypeError):
        first.rows[0][0] = "changed"
    assert "00123" not in repr(first)
    assert first.raw_content_sha256 not in repr(first)
    assert first.snapshot_identity not in repr(first)


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"content_length": 500}, "upload_incomplete"),
        ({"content_length": 1}, "content_mismatch"),
        ({"content_length": -1}, "content_mismatch"),
        ({"content_length": True}, "content_mismatch"),
        ({"content_length": "12"}, "content_mismatch"),
        ({"content_sha256": "0" * 64}, "content_mismatch"),
        ({"content_sha256": "PRIVATE_HASH_CANARY"}, "content_mismatch"),
        ({"content_sha256": None}, "content_mismatch"),
        ({"media_type": "PRIVATE_FILENAME_CANARY.xlsx"}, "unsupported_media_type"),
        ({"media_type": "text/csv; charset=utf-16"}, "unsupported_media_type"),
    ],
)
def test_incomplete_or_mismatched_content_has_closed_errors(changes, code, caplog):
    with pytest.raises(api().CsvSnapshotError) as rejected:
        parse(b"name\nPRIVATE_ROW_CANARY\n", **changes)
    assert rejected.value.code == code
    assert rejected.value.__cause__ is None
    assert rejected.value.__context__ is None
    assert "CANARY" not in str(rejected.value)
    assert "CANARY" not in caplog.text


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"name\n",
        b"\xef\xbb\xbf",
        b"\xef\xbb\xbf\xef\xbb\xbfname\nA\n",
        b"name\n\xff\n",
        b"name\n\xc0\xaf\n",
        b"name\n\x00\n",
        b"name,weight\nA\n",
        b"name,weight\nA,1,extra\n",
        b"name,name\nA,B\n",
        b",weight\nA,1\n",
        b"  ,weight\nA,1\n",
        b"name\n\n",
        b"\nA\n",
        b"name\nA\n\n",
        b'name\n"PRIVATE_ROW_CANARY\n',
        b'name\nPRI"VATE_ROW_CANARY\n',
        b'name\n"PRIVATE_ROW_CANARY"tail\n',
        b'name\n "PRIVATE_ROW_CANARY"\n',
        b"name\rA\r",
        b"name;weight\nA;1\n",
        b"name\tweight\nA\t1\n",
        b"name|weight\nA|1\n",
        b"PK\x03\x04PRIVATE_FILENAME_CANARY.zip",
        b"PK\x05\x06empty.zip",
        b"\x1f\x8bPRIVATE_FILENAME_CANARY.gz",
        b"BZh9archive",
        b"\xfd7zXZ\x00archive",
        b"7z\xbc\xaf\x27\x1carchive",
        b"Rar!\x1a\x07archive",
        b"\xd0\xcf\x11\xe0xls",
        b"SQLite format 3\x00database",
        b"%PDF-1.7\nA\n",
        b'{"name":"PRIVATE_ROW_CANARY"}\n',
        b'["name"]\n["A"]\n',
        b" <?xml version='1.0'?><name>A</name>\n",
        b"\xff\xfename\x00\n\x00A\x00\n\x00",
    ],
)
def test_unsupported_or_malformed_csv_fails_without_private_error_context(data, caplog):
    with pytest.raises(api().CsvSnapshotError) as rejected:
        parse(data)
    assert rejected.value.code == "invalid_csv"
    assert rejected.value.__cause__ is None
    assert rejected.value.__context__ is None
    assert "CANARY" not in str(rejected.value)
    assert "CANARY" not in caplog.text


def assert_limit(data, **changes):
    with pytest.raises(api().CsvSnapshotError) as rejected:
        parse(data, **changes)
    assert rejected.value.code == "source_limit_exceeded"
    assert rejected.value.__cause__ is None
    assert rejected.value.__context__ is None


def test_caps_are_fixed_and_include_headers_and_encoded_field_bytes():
    module = api()
    assert module.MAX_RAW_BYTES == 1024 * 1024
    assert module.MAX_NORMALIZED_BYTES == 2 * 1024 * 1024
    assert module.MAX_DATA_ROWS == 10000
    assert module.MAX_COLUMNS == 64
    assert module.MAX_FIELD_BYTES == 16 * 1024
    header = b"h" * module.MAX_FIELD_BYTES
    assert parse(header + b"\nx\n").headers == (header.decode(),)
    assert_limit(header + b"h\nx\n")
    value = "名" * 5461 + "x"
    assert len(value.encode()) == module.MAX_FIELD_BYTES
    assert parse(("notes\n" + value + "\n").encode()).rows == ((value,),)
    assert_limit(("notes\n" + value + "x\n").encode())


def test_record_and_column_caps_are_logical_records_not_physical_lines():
    assert parse(b"h\n" + b"x\n" * 10000).row_count == 10000
    assert_limit(b"h\n" + b"x\n" * 10001)
    header = ",".join(f"h{i}" for i in range(64))
    body = ",".join("x" for _ in range(64))
    assert parse(f"{header}\n{body}\n".encode()).column_count == 64
    assert_limit(f"{header},extra\n{body},x\n".encode())
    multiline = b'h\n"a\nb\rc\r\nd"\n'
    assert parse(multiline).rows == (("a\nb\rc\r\nd",),)


def test_raw_limit_and_normalized_overhead_are_both_bounded():
    budget = api().MAX_RAW_BYTES - len(b"notes\n")
    records = []
    while budget > api().MAX_FIELD_BYTES + 1:
        records.append(b"x" * api().MAX_FIELD_BYTES + b"\n")
        budget -= api().MAX_FIELD_BYTES + 1
    records.append(b"x" * (budget - 1) + b"\n")
    data = b"notes\n" + b"".join(records)
    assert len(data) == api().MAX_RAW_BYTES
    assert parse(data).row_count == len(records)
    assert_limit(data + b"\n")
    assert_limit(b"h\nx\n", content_length=api().MAX_RAW_BYTES + 1)
    header = ",".join(f"h{i}" for i in range(64)).encode() + b"\n"
    # Small raw bytes can still exceed canonical length-prefix storage bounds.
    expanded = header + (b"," * 63 + b"\n") * 8200
    assert len(expanded) < api().MAX_RAW_BYTES
    assert_limit(expanded)


@pytest.mark.parametrize(
    "value",
    ["=SUM(A1:A3)", "+command", "-123", "@command", "\t=link", "\r=link", "  =link"],
)
def test_formula_looking_values_are_inert_exact_strings(value):
    import csv
    import io

    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["notes"])
    writer.writerow([value])
    assert parse(stream.getvalue().encode()).rows == ((value,),)


def test_counts_projection_never_contains_private_values_or_hashes():
    snapshot = parse(b"PRIVATE_HEADER_CANARY,postal_code\nPRIVATE_ROW_CANARY,00123\n")
    public = snapshot.public_counts()
    assert public == {"format": "csv", "row_count": 1, "column_count": 2}
    assert "CANARY" not in repr(public)
    assert snapshot.raw_content_sha256 not in repr(public)
    assert snapshot.snapshot_identity not in repr(public)
    public["row_count"] = 100
    assert snapshot.public_counts()["row_count"] == 1


def test_normalized_limit_exact_boundary_and_escaped_field_accounting():
    import csv
    import io

    module = api()
    headers = [f"h{i}" for i in range(64)]
    count = 8000
    base = (
        len(module.PARSER_PROFILE.encode())
        + 4
        + sum(4 + len(h.encode()) for h in headers)
    )
    base += count * (4 + 64 * 4)
    gap = module.MAX_NORMALIZED_BYTES - base
    first = min(gap, module.MAX_FIELD_BYTES)
    second = gap - first
    assert 0 <= second < module.MAX_FIELD_BYTES

    def content(extra):
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(headers)
        writer.writerow(["x" * first, "y" * (second + extra), *([""] * 62)])
        writer.writerows([[""] * 64] * (count - 1))
        return stream.getvalue().encode()

    assert parse(content(0)).row_count == count
    assert_limit(content(1))
    value = '"' * module.MAX_FIELD_BYTES
    exact = b'h\n"' + value.replace('"', '""').encode() + b'"\n'
    assert parse(exact).rows == ((value,),)
    assert_limit(b'h\n"' + (value + '"').replace('"', '""').encode() + b'"\n')


def test_valid_writer_variants_preserve_values_and_normalized_identity():
    import csv
    import io
    import random

    rng = random.Random(81)
    alphabet = [
        "a",
        "0",
        " ",
        ",",
        '"',
        "\r",
        "\n",
        "\t",
        "名",
        "é",
        "🙂",
        "\ufeff",
        "=",
    ]
    for _ in range(200):
        width = rng.randrange(1, 9)
        headers = tuple(f"h{i}" for i in range(width))
        rows = tuple(
            tuple(
                "".join(rng.choices(alphabet, k=rng.randrange(15)))
                for _ in range(width)
            )
            for _ in range(rng.randrange(1, 6))
        )
        snapshots = []
        for quoting in (csv.QUOTE_MINIMAL, csv.QUOTE_ALL):
            stream = io.StringIO(newline="")
            writer = csv.writer(stream, quoting=quoting, lineterminator="\r\n")
            writer.writerow(headers)
            writer.writerows(rows)
            snapshots.append(parse(stream.getvalue().encode()))
        assert all(
            snapshot.headers == headers and snapshot.rows == rows
            for snapshot in snapshots
        )
        assert snapshots[0].snapshot_identity == snapshots[1].snapshot_identity


def test_underlying_parser_error_is_closed_without_exception_chaining(
    monkeypatch, caplog
):
    import csv

    def failed_parser(*args, **kwargs):
        raise csv.Error("PRIVATE_PARSER_CANARY")

    monkeypatch.setattr(api().csv, "reader", failed_parser)
    with pytest.raises(api().CsvSnapshotError) as rejected:
        parse(b"name\nPRIVATE_ROW_CANARY\n")
    assert rejected.value.code == "invalid_csv"
    assert rejected.value.__cause__ is None
    assert rejected.value.__context__ is None
    assert "CANARY" not in str(rejected.value) + caplog.text


@pytest.mark.parametrize(
    "header", ["name,name", "Name,name", "name, name ", "name,   "]
)
def test_ambiguous_or_empty_trimmed_casefolded_headers_are_rejected(header):
    with pytest.raises(api().CsvSnapshotError) as rejected:
        parse(f"{header}\nA,B\n".encode())
    assert rejected.value.code == "invalid_csv"


def test_lower_ambient_csv_limit_fails_closed_without_mutating_it():
    import csv

    previous = csv.field_size_limit()
    try:
        csv.field_size_limit(4)
        with pytest.raises(api().CsvSnapshotError) as rejected:
            parse(b"head\n12345\n")
        assert rejected.value.code == "invalid_csv"
        assert rejected.value.__cause__ is None
        assert rejected.value.__context__ is None
        assert csv.field_size_limit() == 4
    finally:
        csv.field_size_limit(previous)


def test_package_configuration_discovers_this_exact_importable_module():
    import tomllib
    from pathlib import Path

    from setuptools import find_namespace_packages, find_packages

    root = Path(__file__).resolve().parents[3]
    configuration = tomllib.loads((root / "pyproject.toml").read_text())
    find = configuration["tool"]["setuptools"]["packages"]["find"]
    discover = (
        find_namespace_packages if find.get("namespaces", True) else find_packages
    )
    packages = {
        package
        for directory in find.get("where", ["."])
        for package in discover(
            where=str(root / directory),
            include=find.get("include", ["*"]),
            exclude=find.get("exclude", []),
        )
    }
    assert "src.services.source_ingress" in packages
    assert (
        Path(api().__file__).resolve()
        == root / "src/services/source_ingress/csv_snapshot.py"
    )
