"""Pydantic schemas for conversation API endpoints.

Defines the request/response contracts for the agent-driven SSE
conversation flow that replaces the legacy command endpoint.
"""

from pydantic import BaseModel, Field


class CreateConversationResponse(BaseModel):
    """Response for creating a new conversation session."""

    session_id: str


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
