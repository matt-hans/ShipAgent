"""Canonical provider-visible status capability vocabulary.

Two families share the status ``capabilities`` field: workflow capability codes
(the findings-branch vocabulary) and relay tool names (what the desktop relay
target publishes today). Both are admitted by the public schema; only relay
tool names are forwarded by the control plane, so the relay filter and the
schema enum cannot drift apart.
"""

WORKFLOW_CAPABILITY_CODES = (
    "shipment_ingress",
    "address_validation",
    "rate_shopping",
    "shipment_preview",
    "shipment_execution",
    "job_status",
    "label_handoff",
)

# Tool-name capabilities the relay execution target reports today.
RELAY_TOOL_CAPABILITIES = (
    "get_shipagent_status",
    "rate_shipment",
)

SHIPAGENT_CAPABILITY_CODES = (*WORKFLOW_CAPABILITY_CODES, *RELAY_TOOL_CAPABILITIES)

PUBLIC_STATUS_CAPABILITIES = frozenset(RELAY_TOOL_CAPABILITIES)
