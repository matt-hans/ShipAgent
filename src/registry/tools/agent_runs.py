"""Dormant full-agent lifecycle contracts; production admission stays disabled."""

from src.registry.identifiers import ShipAgentIdFamily, shipagent_id_schema
from src.registry.models import SideEffectClass
from src.registry.tools.public import public_tool
from src.registry.tools.schema import object_schema

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
            "enum": ["queued", "running", "completed", "failed"],
        },
        "outcome": {
            "type": "string",
            "enum": [
                "pending",
                "planning_completed",
                "provider_failed",
                "interrupted",
                "model_timeout",
            ],
        },
        "expires_at": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
            "minLength": 20,
            "maxLength": 20,
        },
        "poll_after_seconds": {"type": "integer", "minimum": 0, "maximum": 60},
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
]
