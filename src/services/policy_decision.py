"""Provider-neutral tool-policy decisions.

Policy gates answer one question: is this tool call blocked before any gateway
effect? An allowed decision never carries approval or purchase authority; the
workflow-level preview/confirmation guards remain the only execution path.
Runtime adapters project decisions into their own wire formats; this module
must not import any vendor SDK or know a vendor envelope shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PolicyDenialCode(str, Enum):
    """Stable, provider-neutral reasons a tool call can be denied."""

    RAW_SQL_NOT_ALLOWED = "raw_sql_not_allowed"
    INVALID_FILTER_STRUCTURE = "invalid_filter_structure"
    RAW_CARRIER_CALL_NOT_ALLOWED = "raw_carrier_call_not_allowed"
    DIRECT_SHIPMENT_CREATION_NOT_ALLOWED = "direct_shipment_creation_not_allowed"
    INVALID_TOOL_INPUT = "invalid_tool_input"


GENERIC_DENIAL_REASON = "Tool call denied by policy."


@dataclass(frozen=True)
class PolicyDecision:
    """Allowed/denied outcome of a pre-tool policy check.

    ``reason`` is safe to show to a model or end user: it is fixed text, plus
    at most canonical identifiers (banned key names from a fixed set, the
    denied tool name) and never arbitrary caller-supplied values. (The legacy Claude hook adapter
    keeps its detailed validation text for backward compatibility.)
    """

    allowed: bool
    code: PolicyDenialCode | None = None
    reason: str = ""

    @classmethod
    def allow(cls) -> PolicyDecision:
        return cls(allowed=True)

    @classmethod
    def deny(cls, code: PolicyDenialCode, reason: str) -> PolicyDecision:
        return cls(allowed=False, code=code, reason=reason or GENERIC_DENIAL_REASON)
