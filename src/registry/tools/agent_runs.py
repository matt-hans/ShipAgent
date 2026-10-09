"""Dormant full-agent lifecycle contracts; production admission stays disabled."""

from src.registry.identifiers import ShipAgentIdFamily, shipagent_id_schema
from src.registry.models import SideEffectClass
from src.registry.tools.public import public_tool
from src.registry.tools.schema import object_schema
from src.services.agent_runs.clarification import CLARIFICATION_QUESTIONS

RUN_RESULT_SCHEMA = object_schema(
    {
        "run_reference": shipagent_id_schema(
            ShipAgentIdFamily.AGENT_RUN, "Opaque reference to one accepted agent run."
        ),
        "conversation_reference": shipagent_id_schema(
            ShipAgentIdFamily.CONVERSATION,
            "Opaque reference to the owning conversation.",
        ),
        "revision": {"type": "integer", "minimum": 1, "maximum": 2147483647},
        "state": {
            "type": "string",
            "enum": [
                "queued",
                "running",
                "waiting_for_input",
                "completed",
                "failed",
                "cancelled",
            ],
        },
        "outcome": {
            "type": "string",
            "enum": [
                "pending",
                "planning_completed",
                "provider_failed",
                "interrupted",
                "model_timeout",
                "cancelled",
                "clarification_required",
            ],
        },
        "expires_at": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
            "minLength": 20,
            "maxLength": 20,
        },
        "poll_after_seconds": {"type": "integer", "minimum": 0, "maximum": 60},
        "conversation_revision": {
            "type": "integer",
            "minimum": 1,
            "maximum": 2147483647,
        },
        "conversation_state": {
            "type": "string",
            "enum": ["active", "waiting_for_input", "completed", "failed", "cancelled"],
        },
        "clarification": {
            **object_schema(
                {
                    "code": {"type": "string", "enum": list(CLARIFICATION_QUESTIONS)},
                    "question": {
                        "type": "string",
                        "enum": list(CLARIFICATION_QUESTIONS.values()),
                    },
                },
                ["code", "question"],
            ),
            "enum": [
                {"code": code, "question": question}
                for code, question in CLARIFICATION_QUESTIONS.items()
            ],
        },
    },
    [
        "run_reference",
        "conversation_reference",
        "revision",
        "state",
        "outcome",
        "expires_at",
        "poll_after_seconds",
    ],
)

AGENT_RUN_TOOLS = [
    public_tool(
        "submit_shipagent_task",
        "Start a ShipAgent planning task",
        "Accept a source-free ShipAgent planning task. This creates durable state and may use the configured model budget; it cannot buy shipping or run workflow tools.",
        SideEffectClass.agent_work,
        ["shipagent.preview"],
        object_schema(
            {
                "task": {
                    "type": "string",
                    "pattern": r"^[\s\S]{1,8192}$",
                    "minLength": 1,
                    "maxLength": 8192,
                },
                "mode": {"type": "string", "enum": ["source_free"]},
                "request_key": {
                    "type": "string",
                    "pattern": r"^[A-Za-z0-9_.-]{8,128}$",
                    "minLength": 8,
                    "maxLength": 128,
                },
            },
            ["task", "mode", "request_key"],
        ),
        RUN_RESULT_SCHEMA,
        hosted_readiness="not_ready",
        execution_target_required=True,
        notes="Synthetic source-free tracer only. No production export or complete lifecycle qualification.",
    ).model_copy(update={"rate_limit_class": "write", "call_repetition": "idempotent"}),
    public_tool(
        "continue_shipagent_task",
        "Continue a ShipAgent planning task",
        "Answer the current waiting planning turn at its exact conversation revision. This accepts a new model turn under the original lifetime; it cannot approve or execute shipping.",
        SideEffectClass.agent_work,
        ["shipagent.preview"],
        object_schema(
            {
                "conversation_reference": shipagent_id_schema(
                    ShipAgentIdFamily.CONVERSATION, "The owning Conversation Reference."
                ),
                "run_reference": shipagent_id_schema(
                    ShipAgentIdFamily.AGENT_RUN,
                    "The exact current waiting Agent Run Reference.",
                ),
                "expected_revision": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 2147483646,
                    "description": "The current conversation revision that owns the waiting turn.",
                },
                "task": {
                    "type": "string",
                    "pattern": r"^[\s\S]{1,8192}$",
                    "minLength": 1,
                    "maxLength": 8192,
                },
                "request_key": {
                    "type": "string",
                    "pattern": r"^[A-Za-z0-9_.-]{8,128}$",
                    "minLength": 8,
                    "maxLength": 128,
                },
            },
            [
                "conversation_reference",
                "run_reference",
                "expected_revision",
                "task",
                "request_key",
            ],
        ),
        RUN_RESULT_SCHEMA,
        hosted_readiness="not_ready",
        execution_target_required=True,
        notes="Synthetic trusted epoch-bound continuation only. Legacy unbound runs cannot continue; production export remains disabled.",
    ).model_copy(update={"rate_limit_class": "write", "call_repetition": "idempotent"}),
    public_tool(
        "read_shipagent_run",
        "Read a ShipAgent planning run",
        "Read one authorized accepted run's bounded status. This never starts a model turn, creates a shipping job or retries an interrupted operation.",
        SideEffectClass.read,
        ["shipagent.status"],
        object_schema(
            {
                "run_reference": shipagent_id_schema(
                    ShipAgentIdFamily.AGENT_RUN, "The accepted Agent Run Reference."
                )
            },
            ["run_reference"],
        ),
        RUN_RESULT_SCHEMA,
        hosted_readiness="not_ready",
        execution_target_required=True,
        notes="Reference-scoped synthetic tracer. Production export remains disabled.",
    ).model_copy(update={"rate_limit_class": "read", "call_repetition": "poll"}),
    public_tool(
        "cancel_shipagent_run",
        "Cancel a ShipAgent planning run",
        "Cancel future model work or invalidate the exact current waiting follow-up. This preserves completed history and accepted effects; it does not refund charges or prove an in-flight provider request stopped.",
        SideEffectClass.agent_work,
        ["shipagent.preview"],
        object_schema(
            {
                "run_reference": shipagent_id_schema(
                    ShipAgentIdFamily.AGENT_RUN, "The accepted Agent Run Reference."
                )
            },
            ["run_reference"],
        ),
        RUN_RESULT_SCHEMA,
        hosted_readiness="not_ready",
        execution_target_required=True,
        notes="Synthetic source-free cancellation only. Production export remains disabled; no approval or shipment mutation is authorized.",
    ).model_copy(update={"rate_limit_class": "write", "call_repetition": "idempotent"}),
]
