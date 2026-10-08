"""Exact legacy wire decoder from ShipAgent main 6982504 (before issue 67).

Keep this fixture frozen: it proves existing status traffic remains readable by
an older desktop's strict decoder, without runtime dependence on Git history.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RelayProtocolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RelayInvocationEnvelope(RelayProtocolModel):
    type: Literal["relay.invoke"] = "relay.invoke"
    relay_session_id: str
    sequence: int = Field(ge=1)
    relay_invocation_id: str
    tool_name: str
    arguments: dict[str, object] = Field(default_factory=dict)
    input_hash: str
    deadline_at: datetime
    idempotency_key: str
    audit_correlation_id: str
