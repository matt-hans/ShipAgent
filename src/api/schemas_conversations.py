"""Pydantic schemas for conversation API endpoints.

Defines the request/response contracts for the agent-driven SSE
conversation flow that replaces the legacy command endpoint.
"""

from pydantic import BaseModel, Field


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
