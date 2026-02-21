"""Pydantic schemas for conversation API endpoints.

Defines the request/response contracts for the agent-driven SSE
conversation flow that replaces the legacy command endpoint.
"""

from typing import Literal

from pydantic import BaseModel, Field

# UPS document type code → human-readable label mapping.
DOCUMENT_TYPE_LABELS: dict[str, str] = {
    "002": "Commercial Invoice",
    "003": "Certificate of Origin",
    "004": "NAFTA Certificate",
    "005": "Partial Invoice",
    "006": "Packing List",
    "007": "Customer Generated Forms",
    "008": "Air Freight Invoice",
    "009": "Proforma Invoice",
    "010": "SED",
    "011": "Weight Certificate",
}


class CreateConversationRequest(BaseModel):
    """Optional request body for creating a conversation session.

    All fields are optional with safe defaults for backward compatibility.
    Existing clients that POST with no body continue to work.
    """

    interactive_shipping: bool = Field(
        default=False,
        description="Enable interactive single-shipment creation via UPS MCP elicitation",
    )


class CreateConversationResponse(BaseModel):
    """Response for creating a new conversation session."""

    session_id: str
    interactive_shipping: bool = Field(
        default=False,
        description="Effective interactive_shipping mode for this session",
    )


class SendMessageRequest(BaseModel):
    """Request for sending a user message to the conversation agent."""

    content: str = Field(..., min_length=1, description="User message text")


class SendMessageResponse(BaseModel):
    """Response for accepted user message."""

    status: str  # "accepted"
    session_id: str


class ConversationHistoryMessage(BaseModel):
    """A single message in conversation history."""

    role: str
    content: str
    timestamp: str


class ConversationHistoryResponse(BaseModel):
    """Response for conversation history."""

    session_id: str
    messages: list[ConversationHistoryMessage]


class UploadDocumentResponse(BaseModel):
    """Response for the upload-document endpoint."""

    success: bool
    file_name: str
    file_format: str
    file_size_bytes: int


# === Chat Session Persistence Schemas ===


class ChatSessionSummary(BaseModel):
    """Lightweight session summary for sidebar listing."""

    id: str
    title: str | None
    mode: Literal["batch", "interactive"]
    created_at: str
    updated_at: str
    message_count: int


class PersistedMessageResponse(BaseModel):
    """Persisted message for history display."""

    id: str
    role: Literal["user", "assistant", "system"]
    message_type: Literal["text", "system_artifact", "error"]
    content: str
    metadata: dict | None
    sequence: int
    created_at: str


class SessionDetailResponse(BaseModel):
    """Full session with messages for resume."""

    session: ChatSessionSummary
    messages: list[PersistedMessageResponse]


class UpdateTitleRequest(BaseModel):
    """Request to rename a session."""

    title: str = Field(..., min_length=1, max_length=255)


class SaveArtifactRequest(BaseModel):
    """Request to persist an artifact message to a conversation session."""

    content: str = Field(default="", description="Optional text content")
    metadata: dict = Field(..., description="Artifact metadata (action, payload, etc.)")
