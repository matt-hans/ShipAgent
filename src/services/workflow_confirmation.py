"""Local, session-owned confirmation for auxiliary carrier mutations.

Providers can prepare actions; only the user-facing decision route consumes
one. Payloads and the gateway identity are captured at preparation. No model
argument, quoted token, or natural-language confirmation grants execution.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, StrictStr, field_validator, model_validator

from src.utils.redaction import project_public_artifact

PREVIEW_TTL_SECONDS = 600


class PickupDetails(BaseModel):
    """The exact supported carrier payload, shared by pricing and scheduling."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    pickup_date: StrictStr
    ready_time: StrictStr
    close_time: StrictStr
    address_line: StrictStr
    city: StrictStr
    state: StrictStr
    postal_code: StrictStr
    country_code: StrictStr = "US"
    contact_name: StrictStr
    phone_number: StrictStr

    @field_validator("*")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value:
            raise ValueError("Pickup fields must not be empty.")
        return value

    @model_validator(mode="after")
    def valid_schedule(self) -> PickupDetails:
        if len(self.pickup_date) != 8 or not self.pickup_date.isdigit():
            raise ValueError("Use YYYYMMDD for the pickup date.")
        datetime.strptime(self.pickup_date, "%Y%m%d")
        for value in (self.ready_time, self.close_time):
            if len(value) != 4 or not value.isdigit():
                raise ValueError("Use HHMM for pickup times.")
            datetime.strptime(value, "%H%M")
        if self.ready_time >= self.close_time:
            raise ValueError("Ready time must be before close time.")
        if len(self.country_code) != 2 or not self.country_code.isalpha():
            raise ValueError("Use a two-letter country code.")
        self.country_code = self.country_code.upper()
        return self


def valid_pickup_quote(result: dict[str, Any]) -> bool:
    """Never arm a preview from a failed, missing or non-finite cost."""
    total = result.get("grandTotal")
    if result.get("success") is not True or isinstance(total, bool):
        return False
    try:
        amount = Decimal(str(total))
        return amount.is_finite() and amount >= 0
    except (InvalidOperation, ValueError):
        return False


class WorkflowConfirmationError(ValueError):
    """An expired, cancelled, replaced, or already-used confirmation."""


class WorkflowExecutionError(RuntimeError):
    """The remote outcome is not confirmed; never retry this action automatically."""


@dataclass(frozen=True)
class _PendingAction:
    operation: str
    payload_json: str
    gateway: Any
    expires_at: float


class PendingWorkflowActions:
    """In-memory one-shot actions, owned by exactly one AgentSession."""

    def __init__(self) -> None:
        self._pending: dict[str, _PendingAction] = {}
        self._documents: dict[str, tuple[str, Any]] = {}

    def clear(self) -> None:
        self._pending.clear()

    def revoke_all(self) -> None:
        """Drop both pending authority and local result handles on teardown."""
        self.clear()
        self._documents.clear()

    def register_document(self, document_id: str, gateway: Any) -> str:
        """Expose only an opaque current-flow handle, never document contents."""
        handle = "doc_" + uuid4().hex
        self._documents[handle] = (document_id, gateway)
        while len(self._documents) > 32:
            self._documents.pop(next(iter(self._documents)))
        return handle

    def resolve_document(self, handle: str, gateway: Any) -> str:
        document = self._documents.get(handle)
        if document is None or document[1] is not gateway:
            raise WorkflowConfirmationError(
                "Document handle is unavailable for this session or carrier connection."
            )
        return document[0]

    def invalidate(self, operation: str) -> None:
        self._pending = {
            token: action
            for token, action in self._pending.items()
            if action.operation != operation
        }

    def prepare(self, operation: str, payload: dict[str, Any], gateway: Any) -> str:
        self.invalidate(operation)
        token = uuid4().hex
        self._pending[token] = _PendingAction(
            operation=operation,
            payload_json=json.dumps(payload, sort_keys=True),
            gateway=gateway,
            expires_at=time.monotonic() + PREVIEW_TTL_SECONDS,
        )
        return token

    def take(self, token: str) -> _PendingAction:
        # Consume BEFORE any await, including gateway acquisition. A failure,
        # timeout or cancellation can never turn this action into a retry.
        action = self._pending.pop(token, None)
        if action is None or action.expires_at <= time.monotonic():
            raise WorkflowConfirmationError(
                "Preview is unavailable or expired. Request a new preview."
            )
        return action


async def decide_action(
    actions: PendingWorkflowActions,
    token: str,
    decision: str,
    record_outcome: Any | None = None,
) -> tuple[str, dict[str, Any]] | None:
    """Execute one exact user-confirmed action; cancellation consumes it too."""
    action = actions.take(token)
    if decision == "cancel":
        return None
    if decision != "confirm":
        raise WorkflowConfirmationError("Invalid confirmation decision.")

    from src.services.gateway_provider import get_ups_gateway

    dispatched = False

    def record_unconfirmed() -> None:
        if dispatched and record_outcome is not None:
            pickup = action.operation in {"schedule_pickup", "cancel_pickup"}
            record_outcome(
                "pickup_result" if pickup else "paperless_result",
                {
                    "action": {
                        "schedule_pickup": "scheduled",
                        "cancel_pickup": "cancelled",
                        "push_document": "pushed",
                        "delete_document": "deleted",
                    }[action.operation],
                    "success": False,
                    "outcome": "unconfirmed",
                    "message": "Carrier outcome is unconfirmed. Check its status before requesting a new action; this confirmation cannot be retried.",
                },
            )

    try:
        gateway = await get_ups_gateway()
        if gateway is not action.gateway:
            raise WorkflowConfirmationError(
                "Carrier connection changed. Request a new preview."
            )
        payload = json.loads(action.payload_json)
        if action.operation == "schedule_pickup":
            dispatched = True
            result = await gateway.schedule_pickup(**payload)
            prn = result.get("prn")
            if (
                result.get("success") is not True
                or not isinstance(prn, str)
                or not prn.strip()
            ):
                raise WorkflowExecutionError()
            return "pickup_result", project_public_artifact(
                {
                    **payload,
                    "action": "scheduled",
                    "success": True,
                    "prn": result["prn"],
                }
            )
        if action.operation in {"cancel_pickup", "push_document", "delete_document"}:
            dispatched = True
            result = await getattr(gateway, action.operation)(**payload)
            if result.get("success") is not True:
                raise WorkflowExecutionError()
            if action.operation == "cancel_pickup":
                return "pickup_result", {
                    **payload,
                    "action": "cancelled",
                    "success": True,
                }
            return "paperless_result", project_public_artifact(
                {
                    **result,
                    "success": True,
                    "action": "pushed"
                    if action.operation == "push_document"
                    else "deleted",
                    "documentId": payload["document_id"],
                    "shipmentIdentifier": payload.get("shipment_identifier"),
                }
            )
        raise WorkflowConfirmationError("Unsupported confirmation action.")
    except asyncio.CancelledError:
        record_unconfirmed()
        raise
    except WorkflowConfirmationError:
        raise
    except Exception as exc:
        record_unconfirmed()
        # The remote side may already have committed. No automatic retry or
        # re-arming the preview; keep carrier payloads out of logs and errors.
        raise WorkflowExecutionError(
            "Carrier outcome is unconfirmed. Check its status before requesting "
            "a new action; this confirmation cannot be retried."
        ) from exc
