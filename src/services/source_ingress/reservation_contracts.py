"""Bounded target-private metadata; these values grant no source authority."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from src.registry.identifiers import ShipAgentIdFamily, parse_shipagent_id
from src.services.source_ingress.csv_snapshot import MAX_RAW_BYTES, PARSER_PROFILE

MAX_IDENTITY_BYTES = 256
MAX_KEY_CHARACTERS = 128
MAX_KEY_BYTES = 512
MAX_UPLOAD_LIFETIME = 300
MAX_SOURCE_LIFETIME = 86400
MAX_SQLITE_INTEGER = 2**63 - 1
MEDIA_TYPE = "text/csv"

_ERRORS = {
    "reservation_unavailable": "Source reservation is unavailable.",
    "reservation_expired": "Source reservation has expired.",
    "request_conflict": "Source reservation request conflicts with its prior input.",
    "source_limit_exceeded": "Source reservation exceeds a supported limit.",
    "invalid_request": "Source reservation metadata is invalid.",
}


class ReservationError(ValueError):
    """Closed messages without caller metadata or storage exception details."""

    def __init__(self, code: str) -> None:
        if code not in _ERRORS:
            raise ValueError("Unknown source reservation error code.")
        self.code = code
        super().__init__(_ERRORS[code])


def require_private_text(value: str, *, key: bool = False) -> None:
    """Validate exact opaque text without normalizing its identity."""
    if type(value) is not str or not value:
        raise ReservationError("invalid_request")
    if key and len(value) > MAX_KEY_CHARACTERS:
        raise ReservationError("invalid_request")
    try:
        encoded_length = len(value.encode("utf-8"))
    except UnicodeError:
        raise ReservationError("invalid_request") from None
    if encoded_length > (MAX_KEY_BYTES if key else MAX_IDENTITY_BYTES) or any(
        unicodedata.category(character) in {"Cc", "Cf"} for character in value
    ):
        raise ReservationError("invalid_request")


def require_timestamp(value: int, *, zero_allowed: bool = False) -> None:
    if (
        type(value) is not int
        or not (0 if zero_allowed else 1) <= value <= MAX_SQLITE_INTEGER
    ):
        raise ReservationError("invalid_request")


@dataclass(frozen=True, slots=True, repr=False)
class ReservationRequest:
    request_key: str
    content_length: int
    content_sha256: str
    media_type: str = MEDIA_TYPE
    parser_profile: str = PARSER_PROFILE

    def __post_init__(self) -> None:
        require_private_text(self.request_key, key=True)
        if (
            type(self.content_length) is not int
            or not 1 <= self.content_length <= MAX_RAW_BYTES
            or type(self.content_sha256) is not str
            or re.fullmatch(r"[0-9a-f]{64}", self.content_sha256) is None
            or type(self.media_type) is not str
            or self.media_type != MEDIA_TYPE
            or type(self.parser_profile) is not str
            or self.parser_profile != PARSER_PROFILE
        ):
            raise ReservationError("invalid_request")


@dataclass(frozen=True, slots=True, repr=False)
class SourceOperatorContext:
    principal_reference: str

    def __post_init__(self) -> None:
        require_private_text(self.principal_reference)


@dataclass(frozen=True, slots=True, repr=False)
class ResolvedSourceAuthority:
    account_id: str
    provider_connection_id: str
    link_epoch: str
    execution_target_id: str
    target_fingerprint: str
    purpose: Literal["operator_source_setup"]
    authorization_expires_at: int

    def __post_init__(self) -> None:
        for value in (
            self.account_id,
            self.provider_connection_id,
            self.execution_target_id,
            self.target_fingerprint,
        ):
            require_private_text(value)
        require_private_text(self.link_epoch, key=True)
        require_timestamp(self.authorization_expires_at)
        if type(self.purpose) is not str or self.purpose != "operator_source_setup":
            raise ReservationError("invalid_request")


@dataclass(frozen=True, slots=True, repr=False)
class ReservationNamespace:
    account_id: str
    provider_connection_id: str
    link_epoch: str
    conversation_reference: str
    execution_target_id: str
    target_fingerprint: str
    request_key: str
    operation: Literal["upload"] = "upload"

    def __post_init__(self) -> None:
        for value in (
            self.account_id,
            self.provider_connection_id,
            self.execution_target_id,
            self.target_fingerprint,
        ):
            require_private_text(value)
        require_private_text(self.link_epoch, key=True)
        require_private_text(self.request_key, key=True)
        if type(self.conversation_reference) is not str:
            raise ReservationError("invalid_request")
        try:
            parse_shipagent_id(
                self.conversation_reference,
                expected_family=ShipAgentIdFamily.CONVERSATION,
            )
        except ValueError:
            raise ReservationError("invalid_request") from None
        if type(self.operation) is not str or self.operation != "upload":
            raise ReservationError("invalid_request")


@dataclass(frozen=True, slots=True)
class ReservationReceipt:
    reservation_id: str
    status: Literal["reserved"]
    admitted_at: int
    upload_expires_at: int
    prospective_source_expires_at: int

    def __post_init__(self) -> None:
        require_timestamp(self.admitted_at, zero_allowed=True)
        require_timestamp(self.upload_expires_at)
        require_timestamp(self.prospective_source_expires_at)
        if (
            type(self.reservation_id) is not str
            or re.fullmatch(r"[0-9a-f]{32}", self.reservation_id) is None
            or type(self.status) is not str
            or self.status != "reserved"
            or not 0 < self.upload_expires_at - self.admitted_at <= MAX_UPLOAD_LIFETIME
            or not 0
            < self.prospective_source_expires_at - self.admitted_at
            <= MAX_SOURCE_LIFETIME
            or self.upload_expires_at > self.prospective_source_expires_at
        ):
            raise ReservationError("invalid_request")
