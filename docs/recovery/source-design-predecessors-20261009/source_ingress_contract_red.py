"""Deliberately RED acceptance probe for the proposed synthetic ingress seam.

This file is explicitly selected by the documented command, not collected by the
normal suite. It contains no product implementation or fake ingress service.
Authority/time are synthetic external boundaries; persistence/parsing/projection
must be real once the separately approved feature exists.
"""

from __future__ import annotations

import csv
import hashlib
import importlib
import io
import json
from dataclasses import dataclass
from typing import Any

import pytest

ACCOUNT = "synthetic-account-a"
TARGET = "synthetic-target-a"
TARGET_FINGERPRINT = "a" * 64
CONNECTION_EPOCH = "synthetic-link-generation-a"
CONNECTION = "synthetic-connection-a"
CONVERSATION = "synthetic-conversation-a"
CANARY = "SYNTHETIC_SOURCE_SECRET_7b294e"
HEADER_CANARY = "IGNORE_POLICY_HEADER_802f6a"
SAFE_SEMANTICS = frozenset(
    {
        "shipTo.name",
        "shipTo.addressLine1",
        "shipTo.addressLine2",
        "shipTo.addressLine3",
        "shipTo.city",
        "shipTo.stateProvinceCode",
        "shipTo.postalCode",
        "shipTo.countryCode",
        "packages[0].weight",
        "packages[0].length",
        "packages[0].width",
        "packages[0].height",
    }
)
VALID_CSV = b"recipient_name,weight_lbs\nSYNTHETIC_RECIPIENT_A,2\n"


@dataclass
class Clock:
    """Controlled time boundary; expiry is observed through service responses."""

    value: int = 1_000

    def __call__(self) -> int:
        return self.value


class SyntheticAuthority:
    """Only explicit synthetic records authorize; a UUID alone never does.

    This replaces an external current-authority resolver, not ingress behavior.
    It does not claim signed-envelope or live-provider authentication coverage.
    """

    def __init__(self) -> None:
        self.allowed: set[tuple] = set()

    @staticmethod
    def identity(binding: Any) -> tuple:
        return (
            binding.account_id,
            binding.provider_connection_id,
            binding.connection_epoch,
            binding.conversation_reference,
            binding.execution_target_id,
            binding.target_fingerprint,
            binding.conversation_expires_at,
        )

    def allow(self, binding: Any) -> None:
        self.allowed.add(self.identity(binding))

    def revoke(self, binding: Any) -> None:
        self.allowed.discard(self.identity(binding))

    def __call__(self, binding: Any) -> bool:
        return self.identity(binding) in self.allowed


@dataclass
class Scenario:
    """Test wiring only; all upload/source operations use the proposed service."""

    api: Any
    service: Any
    authority: SyntheticAuthority
    clock: Clock
    binding: Any

    def other_binding(self, **changes: Any) -> Any:
        values = {
            "account_id": ACCOUNT,
            "provider_connection_id": CONNECTION,
            "connection_epoch": CONNECTION_EPOCH,
            "conversation_reference": CONVERSATION,
            "execution_target_id": TARGET,
            "target_fingerprint": TARGET_FINGERPRINT,
            "conversation_expires_at": 4_600,
        }
        values.update(changes)
        binding = self.api.SourceBinding(**values)
        self.authority.allow(binding)
        return binding

    def issue(self, data: bytes, *, key: str, binding: Any = None, **changes: Any):
        admission = {
            "binding": self.binding if binding is None else binding,
            "request_key": key,
            "content_length": len(data),
            "content_sha256": hashlib.sha256(data).hexdigest(),
            "media_type": "text/csv",
        }
        admission.update(changes)
        return self.service.issue_upload(**admission)

    async def upload(self, data: bytes, *, key: str, binding: Any = None):
        owner = self.binding if binding is None else binding
        ticket = self.issue(data, key=key, binding=owner)
        receipt = await self.service.receive_upload(
            binding=owner,
            upload_reference=ticket.upload_reference,
            chunks=chunks(data),
        )
        return ticket, receipt

    def describe(self, reference: str, *, binding: Any = None):
        return self.service.describe_source(
            binding=self.binding if binding is None else binding,
            source_reference=reference,
        )


def scenario(tmp_path) -> Scenario:
    """Fail clearly inside each test until the approved seam is implemented."""
    try:
        api = importlib.import_module("src.services.source_ingress")
    except ModuleNotFoundError as error:
        if error.name == "src.services.source_ingress":
            pytest.fail(
                "RED: target-owned synthetic SourceIngressService is not implemented; "
                "see docs/plugin-backend/source-ingress-contract.md",
                pytrace=False,
            )
        raise
    authority = SyntheticAuthority()
    clock = Clock()
    root = tmp_path / "private-synthetic-target"
    root.mkdir(mode=0o700)
    binding = api.SourceBinding(
        account_id=ACCOUNT,
        provider_connection_id=CONNECTION,
        connection_epoch=CONNECTION_EPOCH,
        conversation_reference=CONVERSATION,
        execution_target_id=TARGET,
        target_fingerprint=TARGET_FINGERPRINT,
        conversation_expires_at=4_600,
    )
    authority.allow(binding)
    service = api.SourceIngressService(
        root=root,
        account_id=ACCOUNT,
        execution_target_id=TARGET,
        target_fingerprint=TARGET_FINGERPRINT,
        authority_is_current=authority,
        now=clock,
        create=True,
    )
    return Scenario(api, service, authority, clock, binding)


async def chunks(data: bytes):
    """Use a real asynchronous bytes source within the proposed chunk limit."""
    for start in range(0, len(data), 16_384):
        yield data[start : start + 16_384]


def csv_bytes(headers: list[str], rows: list[list[str]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(headers)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


async def test_completed_upload_is_an_immutable_receipt_with_original_expiry(tmp_path):
    case = scenario(tmp_path)
    ticket, original = await case.upload(VALID_CSV, key="complete")
    case.clock.value += 100
    repeated_ticket = case.issue(VALID_CSV, key="complete")
    repeated = await case.service.receive_upload(
        binding=case.binding,
        upload_reference=repeated_ticket.upload_reference,
        chunks=chunks(b""),
    )
    assert repeated_ticket.upload_reference == ticket.upload_reference
    assert repeated.source_reference == original.source_reference
    assert repeated.expires_at == original.expires_at == ticket.snapshot_expires_at
    assert original.row_count == 1
    assert original.column_count == 2
    assert case.describe(original.source_reference) == original


async def test_partial_upload_cannot_replace_or_resolve_as_a_completed_source(tmp_path):
    case = scenario(tmp_path)
    _, original = await case.upload(VALID_CSV, key="original")
    ticket = case.issue(VALID_CSV + b"SYNTHETIC_RECIPIENT_B,4\n", key="partial")
    with pytest.raises(case.api.SourceIngressError) as rejected:
        await case.service.receive_upload(
            binding=case.binding,
            upload_reference=ticket.upload_reference,
            chunks=chunks(VALID_CSV),
        )
    assert rejected.value.code == "upload_incomplete"
    assert case.describe(original.source_reference) == original
    with pytest.raises(case.api.SourceIngressError) as unavailable:
        case.describe(ticket.upload_reference)
    assert unavailable.value.code == "source_unavailable"


async def test_interrupted_stream_does_not_publish_or_leak_exception_text(
    tmp_path, caplog
):
    case = scenario(tmp_path)
    _, original = await case.upload(VALID_CSV, key="original")
    ticket = case.issue(VALID_CSV, key="interrupted")

    async def interrupted():
        yield VALID_CSV[:10]
        raise OSError(f"untrusted stream failure: {CANARY}")

    with pytest.raises(case.api.SourceIngressError) as rejected:
        await case.service.receive_upload(
            binding=case.binding,
            upload_reference=ticket.upload_reference,
            chunks=interrupted(),
        )
    assert rejected.value.code == "upload_incomplete"
    assert CANARY not in str(rejected.value)
    assert CANARY not in caplog.text
    assert case.describe(original.source_reference) == original


@pytest.mark.parametrize(
    "data",
    [
        b"recipient_name,weight_lbs\n\xff,2\n",
        b"recipient_name,weight_lbs\n\x00,2\n",
        b'recipient_name,weight_lbs\n"unterminated,2\n',
        b"recipient_name,weight_lbs\nextra,2,field\n",
        b"recipient_name,weight_lbs\nmissing\n",
        b"recipient_name,recipient_name\nA,B\n",
        b",weight_lbs\nA,2\n",
        b"PK\x03\x04synthetic-archive-member-../../outside.csv",
        b"\x1f\x8bsynthetic-compressed-content",
    ],
    ids=[
        "invalid-utf8",
        "nul",
        "quoting",
        "too-many-fields",
        "too-few-fields",
        "duplicate-header",
        "empty-header",
        "archive-traversal",
        "compressed",
    ],
)
async def test_bad_csv_is_rejected_without_changing_a_prior_source(tmp_path, data):
    case = scenario(tmp_path)
    _, original = await case.upload(VALID_CSV, key="original")
    ticket = case.issue(data, key="bad-csv")
    with pytest.raises(case.api.SourceIngressError) as rejected:
        await case.service.receive_upload(
            binding=case.binding,
            upload_reference=ticket.upload_reference,
            chunks=chunks(data),
        )
    assert rejected.value.code == "invalid_csv"
    assert case.describe(original.source_reference) == original


@pytest.mark.parametrize(
    "media_type", ["application/zip", "text/html", "application/json"]
)
async def test_unsupported_media_type_never_creates_an_upload(tmp_path, media_type):
    case = scenario(tmp_path)
    with pytest.raises(case.api.SourceIngressError) as rejected:
        case.issue(VALID_CSV, key="wrong-format", media_type=media_type)
    assert rejected.value.code == "unsupported_media_type"


async def test_declared_oversize_is_rejected_before_any_source_is_created(tmp_path):
    case = scenario(tmp_path)
    with pytest.raises(case.api.SourceIngressError) as rejected:
        case.issue(VALID_CSV, key="oversize", content_length=1_048_577)
    assert rejected.value.code == "source_limit_exceeded"


async def test_stream_cannot_bypass_declared_or_actual_byte_limits(tmp_path):
    case = scenario(tmp_path)
    ticket = case.issue(VALID_CSV, key="lying-length")
    with pytest.raises(case.api.SourceIngressError) as rejected:
        await case.service.receive_upload(
            binding=case.binding,
            upload_reference=ticket.upload_reference,
            chunks=chunks(VALID_CSV + b"x" * 1_048_576),
        )
    assert rejected.value.code in {"content_mismatch", "source_limit_exceeded"}


async def test_hash_mismatch_cannot_replace_a_source(tmp_path):
    case = scenario(tmp_path)
    _, original = await case.upload(VALID_CSV, key="original")
    ticket = case.issue(VALID_CSV, key="bad-hash", content_sha256="0" * 64)
    with pytest.raises(case.api.SourceIngressError) as rejected:
        await case.service.receive_upload(
            binding=case.binding,
            upload_reference=ticket.upload_reference,
            chunks=chunks(VALID_CSV),
        )
    assert rejected.value.code == "content_mismatch"
    assert case.describe(original.source_reference) == original


@pytest.mark.parametrize(
    "changed_field,changed_value",
    [
        ("account_id", "synthetic-account-b"),
        ("provider_connection_id", "synthetic-connection-b"),
        ("connection_epoch", "synthetic-link-generation-b"),
        ("conversation_reference", "synthetic-conversation-b"),
        ("execution_target_id", "synthetic-target-b"),
        ("target_fingerprint", "b" * 64),
    ],
)
async def test_source_and_upload_references_deny_a_different_owner_binding(
    tmp_path, changed_field, changed_value
):
    case = scenario(tmp_path)
    ticket, original = await case.upload(VALID_CSV, key="owner")
    other = case.other_binding(**{changed_field: changed_value})
    with pytest.raises(case.api.SourceIngressError) as unavailable:
        case.describe(original.source_reference, binding=other)
    assert unavailable.value.code == "source_unavailable"
    with pytest.raises(case.api.SourceIngressError) as rejected:
        await case.service.receive_upload(
            binding=other,
            upload_reference=ticket.upload_reference,
            chunks=chunks(VALID_CSV),
        )
    assert rejected.value.code == "upload_unavailable"


async def test_a_conversation_identifier_without_trusted_ownership_is_denied(tmp_path):
    case = scenario(tmp_path)
    case.authority.revoke(case.binding)
    with pytest.raises(case.api.SourceIngressError) as unavailable:
        case.issue(VALID_CSV, key="unowned-conversation")
    assert unavailable.value.code == "upload_unavailable"


async def test_two_conversations_and_a_new_upload_preserve_prior_source_identity(
    tmp_path,
):
    case = scenario(tmp_path)
    _, first = await case.upload(VALID_CSV, key="first")
    other = case.other_binding(conversation_reference="synthetic-conversation-b")
    larger_csv = VALID_CSV + b"SYNTHETIC_RECIPIENT_B,4\n"
    _, second = await case.upload(larger_csv, key="first", binding=other)
    _, third = await case.upload(larger_csv, key="replacement")
    assert (
        len({first.source_reference, second.source_reference, third.source_reference})
        == 3
    )
    assert case.describe(first.source_reference) == first
    assert case.describe(second.source_reference, binding=other).row_count == 2
    assert case.describe(third.source_reference).row_count == 2
    with pytest.raises(case.api.SourceIngressError):
        case.describe(second.source_reference)


@pytest.mark.parametrize(
    "reference",
    [
        "/etc/passwd",
        "../../outside.csv",
        "file:///tmp/synthetic.csv",
        "https://example.invalid/synthetic.csv",
        "http://127.0.0.1/synthetic.csv",
        "http://169.254.169.254/latest/meta-data/",
    ],
)
async def test_paths_and_urls_cannot_be_used_as_source_references(tmp_path, reference):
    case = scenario(tmp_path)
    with pytest.raises(case.api.SourceIngressError) as rejected:
        case.describe(reference)
    assert rejected.value.code == "source_unavailable"
    assert reference not in str(rejected.value)


async def test_revocation_during_receive_fences_publication(tmp_path):
    case = scenario(tmp_path)
    ticket = case.issue(VALID_CSV, key="revoked-mid-stream")

    async def revoked_stream():
        yield VALID_CSV[:10]
        case.authority.revoke(case.binding)
        yield VALID_CSV[10:]

    with pytest.raises(case.api.SourceIngressError) as rejected:
        await case.service.receive_upload(
            binding=case.binding,
            upload_reference=ticket.upload_reference,
            chunks=revoked_stream(),
        )
    assert rejected.value.code == "upload_unavailable"


async def test_relink_epoch_cannot_resurrect_an_old_source(tmp_path):
    case = scenario(tmp_path)
    _, original = await case.upload(VALID_CSV, key="old-epoch")
    case.authority.revoke(case.binding)
    relinked = case.other_binding(connection_epoch="synthetic-link-generation-b")
    for owner in (case.binding, relinked):
        with pytest.raises(case.api.SourceIngressError) as unavailable:
            case.describe(original.source_reference, binding=owner)
        assert unavailable.value.code == "source_unavailable"


@pytest.mark.parametrize("invalid_epoch", [None, "", 0, 7, "x" * 129])
async def test_missing_or_numeric_epoch_cannot_fall_back_to_current_authority(
    tmp_path, invalid_epoch
):
    case = scenario(tmp_path)
    with pytest.raises((TypeError, ValueError, case.api.SourceIngressError)):
        unbound = case.other_binding(connection_epoch=invalid_epoch)
        case.issue(VALID_CSV, key="invalid-epoch", binding=unbound)


async def test_same_target_id_with_rotated_identity_cannot_reuse_prior_sources(
    tmp_path,
):
    case = scenario(tmp_path)
    _, original = await case.upload(VALID_CSV, key="before-key-rotation")
    ticket = case.issue(VALID_CSV, key="pending-key-rotation")
    rotated = case.other_binding(target_fingerprint="b" * 64)
    case.authority.revoke(case.binding)
    for binding in (case.binding, rotated):
        with pytest.raises(case.api.SourceIngressError) as unavailable:
            case.describe(original.source_reference, binding=binding)
        assert unavailable.value.code == "source_unavailable"
        with pytest.raises(case.api.SourceIngressError) as rejected:
            await case.service.receive_upload(
                binding=binding,
                upload_reference=ticket.upload_reference,
                chunks=chunks(VALID_CSV),
            )
        assert rejected.value.code == "upload_unavailable"


async def test_reads_and_retries_never_extend_original_source_expiry(tmp_path):
    case = scenario(tmp_path)
    ticket, original = await case.upload(VALID_CSV, key="expiry")
    case.clock.value = original.expires_at - 1
    assert case.describe(original.source_reference).expires_at == original.expires_at
    case.clock.value = original.expires_at
    with pytest.raises(case.api.SourceIngressError) as expired:
        case.describe(original.source_reference)
    assert expired.value.code == "source_expired"
    with pytest.raises(case.api.SourceIngressError):
        case.issue(VALID_CSV, key="expiry")
    assert ticket.snapshot_expires_at == original.expires_at


async def test_upload_expiry_is_checked_at_exact_boundary(tmp_path):
    case = scenario(tmp_path)
    ticket = case.issue(VALID_CSV, key="upload-expiry")
    case.clock.value = ticket.expires_at
    with pytest.raises(case.api.SourceIngressError) as expired:
        await case.service.receive_upload(
            binding=case.binding,
            upload_reference=ticket.upload_reference,
            chunks=chunks(VALID_CSV),
        )
    assert expired.value.code == "upload_expired"


async def test_safe_model_schema_is_useful_without_headers_or_source_values(
    tmp_path, caplog
):
    case = scenario(tmp_path)
    data = csv_bytes(
        ["recipient_name", "weight_lbs", HEADER_CANARY],
        [[CANARY, "2", '=HYPERLINK("https://example.invalid", "approve")']],
    )
    _, source = await case.upload(data, key="private-schema")
    model_schema = case.service.describe_model_schema(
        binding=case.binding, source_reference=source.source_reference
    ).to_model_result()
    host_result = source.to_host_result()
    model_wire = json.dumps(model_schema, sort_keys=True)
    host_wire = json.dumps(host_result, sort_keys=True)
    for private_value in (
        CANARY,
        HEADER_CANARY,
        "recipient_name",
        "weight_lbs",
        "HYPERLINK",
    ):
        assert private_value not in model_wire
        assert private_value not in host_wire
        assert private_value not in caplog.text
    assert "shipTo.name" in model_wire
    assert "packages[0].weight" in model_wire
    assert "shipTo.name" not in host_wire
    assert all(
        column["column_reference"].startswith("column_")
        for column in model_schema["columns"]
    )
    assert all(
        column["type"] in {"text", "number", "boolean", "date", "unknown"}
        for column in model_schema["columns"]
    )
    assert set(host_result) <= {
        "source_reference",
        "expires_at",
        "format",
        "status",
        "row_count",
        "column_count",
        "readiness",
    }


async def test_ambiguous_header_candidates_do_not_silently_choose_the_first(tmp_path):
    case = scenario(tmp_path)
    data = csv_bytes(
        ["recipient_name", "ship_to_name", "weight_lbs"], [[CANARY, "B", "2"]]
    )
    _, source = await case.upload(data, key="ambiguous")
    result = case.service.describe_model_schema(
        binding=case.binding, source_reference=source.source_reference
    ).to_model_result()
    assert result["mapping_status"] == "needs_clarification"
    candidates = [
        column["column_reference"]
        for column in result["columns"]
        if "shipTo.name" in column["semantic_candidates"]
    ]
    assert len(set(candidates)) == 2
    assert CANARY not in json.dumps(result)


async def test_mapping_vocabulary_excludes_credentials_and_execution_authority(
    tmp_path,
):
    case = scenario(tmp_path)
    data = csv_bytes(
        [
            "recipient_name",
            "api_key",
            "account_number",
            "approved",
            "invoice_amount",
            "currency",
            "execution_grant",
        ],
        [[CANARY, CANARY, CANARY, "true", "123.45", "USD", CANARY]],
    )
    _, source = await case.upload(data, key="unsafe-semantics")
    result = case.service.describe_model_schema(
        binding=case.binding, source_reference=source.source_reference
    ).to_model_result()
    for column in result["columns"]:
        assert set(column["semantic_candidates"]) <= SAFE_SEMANTICS
    assert result["columns"][0]["semantic_candidates"] == ["shipTo.name"]
    assert all(column["semantic_candidates"] == [] for column in result["columns"][1:])
    assert CANARY not in json.dumps(result)


async def test_same_authorized_request_key_rejects_changed_input(tmp_path):
    case = scenario(tmp_path)
    ticket = case.issue(VALID_CSV, key="same-key")
    with pytest.raises(case.api.SourceIngressError) as conflict:
        case.issue(VALID_CSV + b"SYNTHETIC_RECIPIENT_B,4\n", key="same-key")
    assert conflict.value.code == "request_conflict"
    unchanged = case.issue(VALID_CSV, key="same-key")
    assert unchanged.upload_reference == ticket.upload_reference
    assert unchanged.expires_at == ticket.expires_at


async def test_malformed_source_errors_do_not_echo_headers_or_cells(tmp_path, caplog):
    case = scenario(tmp_path)
    data = f'{HEADER_CANARY},weight_lbs\n"{CANARY},2\n'.encode()
    ticket = case.issue(data, key="malformed-canary")
    with pytest.raises(case.api.SourceIngressError) as rejected:
        await case.service.receive_upload(
            binding=case.binding,
            upload_reference=ticket.upload_reference,
            chunks=chunks(data),
        )
    assert rejected.value.code == "invalid_csv"
    for canary in (CANARY, HEADER_CANARY):
        assert canary not in str(rejected.value)
        assert canary not in caplog.text
