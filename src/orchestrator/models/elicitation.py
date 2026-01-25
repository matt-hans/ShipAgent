"""Elicitation models for handling ambiguous commands and missing information.

These Pydantic models define the structure of elicitation questions and responses,
following the Claude Agent SDK AskUserQuestion pattern for structured user interaction.

Per Agent SDK docs:
- Max 4 questions per elicitation
- 2-4 options per question recommended
- 60-second timeout for responses
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ElicitationOption(BaseModel):
    """A single option for an elicitation question.

    Represents one selectable choice in a question, with display label
    and optional associated value.

    Attributes:
        id: Unique identifier (e.g., "order_date", "ship_by_date")
        label: Display label (e.g., "Order Date")
        description: Explanation (e.g., "When the order was placed")
        value: Associated value if different from id
    """

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Unique option identifier")
    label: str = Field(..., description="Display label for the option")
    description: str = Field(..., description="Explanation of the option")
    value: Any = Field(default=None, description="Associated value if different from id")


class ElicitationQuestion(BaseModel):
    """A structured question for user elicitation.

    Represents a single question with options for the user to choose from.
    Follows the Claude Agent SDK pattern for AskUserQuestion.

    Attributes:
        id: Unique question identifier
        header: Section header (e.g., "Date Column")
        question: The actual question text
        options: Available choices
        allow_free_text: Allow "Other" responses
        multi_select: Allow multiple selections
        required: Must be answered
    """

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Unique question identifier")
    header: str = Field(..., description="Section header for the question")
    question: str = Field(..., description="The actual question text")
    options: list[ElicitationOption] = Field(
        default_factory=list,
        description="Available choices for the question",
    )
    allow_free_text: bool = Field(
        default=True,
        description="Allow 'Other' free-text responses",
    )
    multi_select: bool = Field(
        default=False,
        description="Allow multiple option selections",
    )
    required: bool = Field(
        default=True,
        description="Whether the question must be answered",
    )


class ElicitationResponse(BaseModel):
    """User response to an elicitation question.

    Captures the user's selection(s) and any free-text input.

    Attributes:
        question_id: Which question was answered
        selected_options: Selected option IDs
        free_text: Custom response if any
        timestamp: When the response was provided
    """

    model_config = ConfigDict(from_attributes=True)

    question_id: str = Field(..., description="ID of the question being answered")
    selected_options: list[str] = Field(
        default_factory=list,
        description="Selected option IDs",
    )
    free_text: Optional[str] = Field(
        default=None,
        description="Custom free-text response if any",
    )
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="When the response was provided",
    )


class ElicitationContext(BaseModel):
    """Full context for an elicitation session.

    Contains all questions, collected responses, and session configuration.
    Per Agent SDK docs, max 4 questions per elicitation with 60-second timeout.

    Attributes:
        questions: List of questions to ask (max 4)
        responses: Collected responses keyed by question_id
        timeout_seconds: Timeout for response (default 60 per Agent SDK)
        complete: Whether all required questions have been answered
    """

    model_config = ConfigDict(from_attributes=True)

    questions: list[ElicitationQuestion] = Field(
        default_factory=list,
        description="Questions to ask (max 4 per Agent SDK)",
    )
    responses: dict[str, ElicitationResponse] = Field(
        default_factory=dict,
        description="Collected responses keyed by question_id",
    )
    timeout_seconds: int = Field(
        default=60,
        description="Timeout for response in seconds (Agent SDK default)",
    )
    complete: bool = Field(
        default=False,
        description="Whether all required questions have been answered",
    )
