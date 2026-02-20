"""System prompt builder for the SDK orchestration agent.

Dynamically builds the agent's system prompt by merging shipping domain
knowledge (service codes, filter rules, workflow) with the current data
source schema. The schema section is refreshed per-message so the agent
always has accurate column information.

Example:
    prompt = build_system_prompt(source_info=svc.get_source_info())
"""

import os
from datetime import datetime

from src.orchestrator.filter_schema_inference import (
    resolve_fulfillment_status_column,
    resolve_total_column,
)
from src.orchestrator.models.filter_spec import FilterOperator
from src.orchestrator.models.intent import SERVICE_ALIASES, ServiceCode
from src.services.data_source_mcp_client import DataSourceInfo
from src.services.filter_constants import BUSINESS_PREDICATES, REGIONS

# International service codes for labeling
_INTERNATIONAL_SERVICES = frozenset({"07", "08", "11", "54", "65"})
_MAX_SCHEMA_SAMPLES = 5
MAX_PROMPT_CONTACTS = 20


def _build_contacts_section(contacts: list[dict]) -> str:
    """Build the saved contacts catalogue for the system prompt.

    Formats contacts as: @handle — City, ST (roles)
    Roles are inferred from use_as_ship_to and use_as_shipper flags.

    Args:
        contacts: List of contact dicts with handle, city, state_province,
                  use_as_ship_to, use_as_shipper keys.

    Returns:
        Formatted string with contacts section, or empty string if no contacts.
    """
    if not contacts:
        return ""

    lines = ["## Saved Contacts", ""]
    lines.append(
        "The user has saved contacts in their address book. When shipping to a "
        "known contact, use `resolve_contact` with the @handle to get the full "
        "address. You can reference contacts by @handle in commands."
    )
    lines.append("")
    lines.append("Available contacts:")

    for c in contacts[:MAX_PROMPT_CONTACTS]:
        handle = c.get("handle", "unknown")
        city = c.get("city", "")
        state = c.get("state_province", "")

        # Build roles list
        roles = []
        if c.get("use_as_ship_to"):
            roles.append("ship_to")
        if c.get("use_as_shipper"):
            roles.append("shipper")
        roles_str = ", ".join(roles) if roles else "no roles"

        location = f"{city}, {state}" if city and state else city or state or "no location"
        lines.append(f"- @{handle} — {location} ({roles_str})")

    if len(contacts) > MAX_PROMPT_CONTACTS:
        lines.append(f"- ... and {len(contacts) - MAX_PROMPT_CONTACTS} more")

    return "\n".join(lines)


def _resolve_sample_char_limit() -> int:
    """Resolve prompt sample truncation length with safe fallback."""
    raw = os.environ.get("SYSTEM_PROMPT_SAMPLE_MAX_CHARS", "50")
    try:
        value = int(raw)
    except ValueError:
        return 50
    return max(10, value)


def _format_schema_sample(value: object, max_chars: int) -> str:
    """Render a sample value with truncation to control prompt growth."""
    rendered = repr(value)
    if len(rendered) <= max_chars:
        return rendered
    return f"{rendered[:max_chars - 3]}..."


def _build_service_table() -> str:
    """Build UPS service code reference table with domestic/international labels.

    Returns:
        Formatted string listing all service codes and their aliases.
    """
    code_to_aliases: dict[str, list[str]] = {}
    for alias, code in SERVICE_ALIASES.items():
        if code.value not in code_to_aliases:
            code_to_aliases[code.value] = []
        code_to_aliases[code.value].append(alias)

    lines = []
    for code_enum in ServiceCode:
        aliases = code_to_aliases.get(code_enum.value, [])
        label = "international" if code_enum.value in _INTERNATIONAL_SERVICES else "domestic"
        lines.append(f"- {code_enum.name} (code {code_enum.value}, {label}): {', '.join(aliases)}")
    return "\n".join(lines)


def _build_schema_section(
    source_info: DataSourceInfo,
    column_samples: dict[str, list] | None = None,
) -> str:
    """Build the dynamic data source schema section.

    Args:
        source_info: Metadata about the connected data source.
        column_samples: Optional sample values per column for filter grounding.

    Returns:
        Formatted string describing the source and its columns.
    """
    lines = [
        f"Source type: {source_info.source_type}",
    ]
    if source_info.file_path:
        lines.append(f"File: {source_info.file_path}")
    lines.append(f"Row count: {source_info.row_count}")
    lines.append("")
    lines.append("Columns:")
    max_chars = _resolve_sample_char_limit()
    for col in source_info.columns:
        nullable = "nullable" if col.nullable else "not null"
        samples = column_samples.get(col.name) if column_samples else None
        if samples:
            sample_str = ", ".join(
                _format_schema_sample(sample, max_chars)
                for sample in samples[:_MAX_SCHEMA_SAMPLES]
            )
            lines.append(f"  - {col.name} ({col.type}, {nullable}) — samples: {sample_str}")
        else:
            lines.append(f"  - {col.name} ({col.type}, {nullable})")
    return "\n".join(lines)


def _build_filter_rules(schema_columns: set[str] | None = None) -> str:
    """Build FilterIntent schema documentation for the batch mode prompt.

    Replaces the legacy SQL filter rules with structured FilterIntent
    instructions. The LLM produces a FilterIntent JSON; deterministic
    tools resolve and compile it to parameterized SQL.

    Args:
        schema_columns: Optional set of column names from the active data source.
            Used to generate schema-aware guidance instead of hardcoded column names.

    Returns:
        Formatted string with FilterIntent schema and operator reference.
    """
    # Build operator reference
    ops = ", ".join(f"`{op.value}`" for op in FilterOperator)

    # Build semantic keys list dynamically from canonical constants
    _semantic_keys_list = ", ".join(
        sorted(REGIONS.keys()) + sorted(BUSINESS_PREDICATES.keys())
    )

    # Build schema-conditional search hints (avoid hardcoded column names)
    _cols = schema_columns or set()
    hint_lines: list[str] = []
    name_cols = [c for c in ("customer_name", "ship_to_name", "name", "recipient_name") if c in _cols]
    if name_cols:
        cols_str = "` or `".join(name_cols)
        hint_lines.append(f"- For person name searches, use `contains_ci` operator on `{cols_str}`.")
    tag_cols = [c for c in ("tags", "tag", "labels") if c in _cols]
    if tag_cols:
        cols_str = "` or `".join(tag_cols)
        hint_lines.append(f"- For tag searches, use `contains_ci` operator on `{cols_str}`.")
    total_col = resolve_total_column(_cols)
    if total_col:
        hint_lines.append(
            f"- For total/amount filters, prefer `{total_col}` for numeric bounds."
        )
    fulfillment_col = resolve_fulfillment_status_column(_cols)
    if fulfillment_col:
        hint_lines.append(
            f"- For fulfillment filters: use `{fulfillment_col}` equals "
            "`\"unfulfilled\"` or `\"fulfilled\"` (not null checks)."
        )
    _schema_hints = "\n".join(hint_lines)

    return f"""
**IMPORTANT: NEVER generate raw SQL.** All filtering uses the FilterIntent JSON schema.

### FilterIntent Schema

To filter data, call `resolve_filter_intent` with a structured FilterIntent JSON.
The deterministic resolver expands semantic references and produces a `filter_spec`
that you pass to `ship_command_pipeline` or `fetch_rows`.

**Workflow:**
1. Build a FilterIntent JSON from the user's request
2. Call `resolve_filter_intent` with the intent
3. If status is RESOLVED: pass the returned `filter_spec` to pipeline/fetch_rows
4. If status is NEEDS_CONFIRMATION: present the `pending_confirmations` to the user for approval, then call `confirm_filter_interpretation` with the `resolution_token` and the **same** `intent` to get a RESOLVED spec
5. If status is UNRESOLVED: present suggestions to the user and ask for clarification

### Available Operators

{ops}

### FilterIntent JSON Structure

```json
{{
  "root": {{
    "logic": "AND",
    "conditions": [
      {{"column": "state", "operator": "eq", "operands": [{{"type": "string", "value": "CA"}}]}},
      {{"column": "total", "operator": "gt", "operands": [{{"type": "number", "value": 100}}]}}
    ]
  }}
}}
```

### Semantic References

For geographic regions and business predicates, use SemanticReference nodes instead of
listing individual values. The resolver expands them deterministically:

```json
{{"semantic_key": "NORTHEAST", "target_column": "state"}}
```

Available semantic keys: {_semantic_keys_list},
and all US state names (e.g., "california" → "CA").

### Rules
- NEVER generate SQL WHERE clauses. Always use FilterIntent JSON.
- ONLY reference columns that exist in the connected data source schema above.
- Use `all_rows=true` (not a FilterIntent) when the user wants all rows shipped.
- For explicit batch shipping commands, attempt one deterministic pass first:
  call `resolve_filter_intent`, then call `ship_command_pipeline` with the result.
- Ask clarifying questions only if tool outputs are unresolved/blocking
  (`UNRESOLVED`, `NEEDS_CONFIRMATION`, or deterministic mismatch errors).
- Never claim a row/order count unless it comes from a tool response field (`total_rows`, `total_count`, or `row_count`).
- If both `total_count` and `returned_count` are present, treat `total_count` as authoritative.
{_schema_hints}
"""


MAX_RESUME_MESSAGES = 30
MAX_RESUME_TOKENS = 4000  # ~16K chars at ~4 chars/token


def _estimate_token_count(text: str) -> int:
    """Rough token estimate at ~4 characters per token.

    Args:
        text: Input text.

    Returns:
        Estimated token count.
    """
    return len(text) // 4


def _build_prior_conversation_section(
    messages: list[dict],
) -> str:
    """Build a prior conversation section for session resume.

    Applies two limits to control prompt size:
    1. MAX_RESUME_MESSAGES — hard cap on message count.
    2. MAX_RESUME_TOKENS — estimated token budget. Messages are
       included newest-first until the budget is exhausted.

    Args:
        messages: List of {role, content} dicts from persisted history.

    Returns:
        Formatted conversation history section, or empty string.
    """
    if not messages:
        return ""

    # Start from the most recent messages and work backwards
    candidates = messages[-MAX_RESUME_MESSAGES:]
    included: list[dict] = []
    token_budget = MAX_RESUME_TOKENS

    for msg in reversed(candidates):
        content = msg.get("content", "")
        # Truncate very long individual messages
        if len(content) > 500:
            content = content[:497] + "..."
        cost = _estimate_token_count(content) + 10  # overhead for role label
        if token_budget - cost < 0 and included:
            break  # budget exhausted
        token_budget -= cost
        included.append({"role": msg.get("role", "unknown"), "content": content})

    included.reverse()  # Restore chronological order

    if not included:
        return ""

    lines = [
        "## Prior Conversation (Resumed Session)",
        "",
        "You are resuming a prior conversation. Here is the recent history:",
        "",
    ]

    omitted = len(messages) - len(included)
    if omitted > 0:
        lines.append(f"({omitted} earlier messages omitted)")
        lines.append("")

    for msg in included:
        lines.append(f"[{msg['role']}]: {msg['content']}")

    return "\n".join(lines)


def build_system_prompt(
    source_info: DataSourceInfo | None = None,
    interactive_shipping: bool = False,
    column_samples: dict[str, list] | None = None,
    contacts: list[dict] | None = None,
    prior_conversation: list[dict] | None = None,
) -> str:
    """Build the complete system prompt for the orchestration agent.

    Merges identity, domain knowledge, filter rules, workflow steps,
    safety rules, and the current data source schema into a single prompt.

    When interactive_shipping is True, includes sections for direct
    single-shipment creation and validation error handling. When False
    (default), these sections are omitted entirely, keeping the agent
    focused on batch operations only.

    Args:
        source_info: Current data source metadata. None if no source connected.
        interactive_shipping: Whether interactive single-shipment mode is enabled.
        column_samples: Optional sample values per column for filter grounding.
        contacts: Optional list of saved contacts for @handle resolution.
        prior_conversation: Optional list of {role, content} dicts for session resume.

    Returns:
        Complete system prompt string.
    """
    current_date = datetime.now().strftime("%Y-%m-%d")
    service_table = _build_service_table()

    # Data source section — interactive mode suppresses schema details.
    if interactive_shipping:
        data_section = (
            "Interactive shipping mode is active. "
            "Single shipment creation is enabled and data-source schema context "
            "is intentionally hidden in this mode. If the user requests batch or "
            "data-source-driven shipping, instruct them to turn Interactive Shipping off."
        )
    elif source_info is not None:
        data_section = _build_schema_section(source_info, column_samples=column_samples)
    else:
        shopify_configured = bool(
            os.environ.get("SHOPIFY_ACCESS_TOKEN")
            and os.environ.get("SHOPIFY_STORE_DOMAIN")
        )
        if shopify_configured:
            data_section = (
                "No data source imported yet, but Shopify credentials are configured "
                "in the environment.\n"
                "You MUST call the connect_shopify tool FIRST to import Shopify orders "
                "before doing anything else. Do not ask the user to connect a source — "
                "just call connect_shopify immediately."
            )
        else:
            data_section = (
                "No data source connected. The user can still use tracking, pickup, "
                "location finder, landed cost, and paperless document tools without a "
                "data source. For batch shipping commands, ask the user to connect a "
                "CSV, Excel, or database source first."
            )

    filter_rules_section = ""
    workflow_section = ""
    interactive_validation_section = ""
    safety_mode_section = ""
    tool_usage_section = ""

    if interactive_shipping:
        filter_rules_section = """
Interactive mode is active:
- Do NOT generate SQL WHERE clauses.
- Do NOT reference data source columns.
- Collect shipment details conversationally from the user.
"""
        workflow_section = """
### Interactive Single Shipment Mode

Interactive Shipping is enabled for single-shipment creation only.

**Your shipper address and UPS account number are auto-populated from configuration.**
You do NOT need to ask for shipper details, account number, or billing information.

**Gather from the user:**
1. Recipient name
2. Recipient address (street, city, state, ZIP)
3. Service preference (required). ALWAYS pass this as the `service` parameter (e.g., "overnight", "Next Day Air", "2nd Day Air", "3 Day Select", "UPS Standard").
4. Package weight in lbs (required)
5. Recipient phone (optional)

Attention name handling:
- Default `ship_to_attention_name` to recipient name automatically.
- Do NOT ask "is recipient name the attention name?" or similar confirmation questions.
- Only pass `ship_to_attention_name` when the user explicitly provides a different attention/contact name.

**Workflow:**
1. Collect shipment details from the user's message
2. If `service` or `weight` is missing, ask a direct follow-up question to elicit it before calling tools
3. Call `preview_interactive_shipment` with the gathered details
4. STOP — the preview card will appear with shipment details, estimated cost, and route-available services
5. If the user refines (e.g., "use Worldwide Saver", "make it 3 lbs"), call `preview_interactive_shipment` again with updated values
6. The system handles confirmation and execution automatically — do not call any other tools

**Important:**
- Do NOT call `mcp__ups__create_shipment` directly — always use `preview_interactive_shipment`
- If the user says "ship from my NYC warehouse at 789 Broadway, New York, NY 10003", pass that as the `ship_from` override parameter
- Do NOT ask for shipper address, account number, or billing details — these come from config

Batch and data-source policy in this mode:
- Do NOT call batch or data-source tools
- If the user requests batch or data-source shipping, instruct them to turn Interactive Shipping off
- If the request is ambiguous between ad-hoc and batch, ask one clarifying question and default to ad-hoc only if explicitly confirmed
"""
        safety_mode_section = """
- In interactive mode, NEVER call batch/data-source tools.
- If the user requests batch/data-source shipping, clearly instruct them to turn Interactive Shipping off.
"""
        tool_usage_section = """
You have deterministic tools available. In interactive mode, use `preview_interactive_shipment`
for shipment creation. Do not attempt batch/data-source tools in this mode.
"""
    else:
        _src_cols = (
            {col.name for col in source_info.columns}
            if source_info is not None
            else None
        )
        filter_rules_section = _build_filter_rules(schema_columns=_src_cols)
        workflow_section = """
### Shipping Commands (default path)

For straightforward shipping commands (for example: "ship all CA orders via Ground"):

1. **Parse + Build FilterIntent**: Build a FilterIntent JSON from the user's request (or use `all_rows=true` for all rows)
2. **Resolve Filter**: Call `resolve_filter_intent` with the FilterIntent to get a `filter_spec`
3. **Single Tool Call**: Call `ship_command_pipeline` with the `filter_spec` and command text. Include `service_code` ONLY when the user explicitly requests a service (e.g., Ground, 2nd Day Air). Include `packaging_type` only when the user explicitly requests a packaging type.
4. **Post-Preview Message**: After preview appears, respond with ONLY one brief sentence:
   "Preview ready — X rows at $Y estimated total. Please review and click Confirm or Cancel."

**Auto-corrections:** When overriding service for a batch, the system auto-resets incompatible packaging (Letter, PAK, Express Box, Tube → Customer Supplied for Ground/3 Day Select). Saturday Delivery is also auto-stripped for non-express services. Auto-corrections appear as warnings in the preview card — no separate user confirmation needed.

Important:
- `ship_command_pipeline` fetches rows internally. Do NOT call `fetch_rows` first.
- For shipping execution requests, NEVER use `fetch_rows` directly. It is exploratory-only.
- NEVER use `all_rows=true` when the command includes qualifiers like regions or business/company terms.

If `ship_command_pipeline` returns an error:
- Missing `filter_spec`/`all_rows` args: immediately call `resolve_filter_intent` and retry `ship_command_pipeline` with the returned `filter_spec`.
- FilterSpec compilation error: fix the intent and retry once.
- UPS/preview failure: report the error with `job_id` and suggest user action.
- Do NOT ask the user to choose a manual fallback for the same command.
- Do not ask clarifying questions before this first deterministic tool pass.

### Data Exploration (non-execution path)

Use this path only for data-inspection requests (show/list/find/count), not shipment execution.
If the user asks to execute shipments, use `ship_command_pipeline`.

1. Check data source
2. Build FilterIntent and call `resolve_filter_intent`
3. Fetch rows with the resolved `filter_spec` (or `all_rows=true` only when user explicitly asks for all rows)
4. Summarize findings from the returned rows/counts

Exploration narration rules:
- Do not narrate inferred counts from samples/pages.
- If a tool response includes both `total_count` and `returned_count`, only cite `total_count`.
"""
        safety_mode_section = """
- If no data source is connected and the user requests a batch operation, do not attempt to fetch rows — ask the user to connect a data source first.
"""
        tool_usage_section = """
You have access to deterministic tools for data operations, job management, and batch processing.
Use them to execute the workflow steps above. Never call the LLM for sub-tasks that tools can handle
deterministically (e.g., SQL validation, column mapping, payload building).
"""

    # Safety rules: common block applies to both modes, batch block only when not interactive.
    common_safety = """
- If the user's command is ambiguous after deterministic tool checks, ask clarifying questions instead of guessing.
- Report errors clearly with the error code and a suggested remediation.
"""

    if interactive_shipping:
        batch_safety = ""
    else:
        batch_safety = """
- You must NEVER execute a batch without user confirmation. Always preview first.
- You must NEVER call batch_execute directly. The frontend handles execution via the Confirm button.
- You must NEVER skip the preview step. The user must see costs before committing.
- Prefer `ship_command_pipeline` first for straightforward shipping commands.
- During multi-tool fallback steps, prefer tool-first execution with minimal narration.
- During fallback, never state speculative counts before an authoritative tool count is returned.
- After preview is ready, respond with ONLY one brief sentence. Do NOT provide row-level or shipment-level details in text.
- After preview is ready, you must NOT call additional tools until the user confirms or cancels.
"""

    # International shipping guidance (batch and interactive modes)
    international_section = ""
    enabled_lanes = os.environ.get("INTERNATIONAL_ENABLED_LANES", "")
    if enabled_lanes:
        lanes_stripped = [lane.strip() for lane in enabled_lanes.split(",") if lane.strip()]
        is_wildcard = "*" in lanes_stripped
        if is_wildcard:
            lanes_display = "All international destinations"
        else:
            lanes_display = ", ".join(lanes_stripped)

        interactive_specific_guidance = ""
        if interactive_shipping:
            interactive_specific_guidance = """
Interactive mode collection requirements:
- ALWAYS pass `ship_to_country` for non-US destinations and collect recipient phone.
- Do NOT ask for recipient attention name when recipient name is already known; default attention to recipient name unless the user specifies a different contact.
- Collect recipient `ship_to_state` (state/province/county code) when required for the destination country (e.g., GB).
- Never copy postal code into `ship_to_state`; if a required state/province is unknown, ask the user explicitly.
- Do NOT ask for shipper phone or attention name — these are auto-populated from environment configuration.
- Collect and pass `commodities` items with description, commodity_code, origin_country, quantity, and unit_value.
- Collect and pass `invoice_currency_code`, `invoice_monetary_value`, `invoice_number`, and `reason_for_export` for international invoice forms.
- For `reason_for_export`, ask a direct choice question when missing (SALE/GIFT/SAMPLE/REPAIR/RETURN/INTERCOMPANY).
- When the user ships internationally, prefer international service codes (07, 08, 11, 54, 65) instead of domestic service codes.
"""

        country_filter_examples = """
Country-based filter examples:
- "ship Canadian orders": ship_to_country = 'CA'
- "orders going to Mexico": ship_to_country = 'MX'
- "orders going to UK": ship_to_country = 'GB'
- "European orders": ship_to_country IN ('DE', 'FR', 'IT', 'ES', 'NL')
- "international orders": ship_to_country != 'US' AND ship_to_country != 'PR'
"""
        if interactive_shipping:
            country_filter_examples = ""

        exemptions_section = """
**Exemptions** (reduced requirements — no description, forms, or commodities needed):
- **UPS Letter** (packaging code "01"): Only contacts and InvoiceLineTotal (where applicable) required.
- **EU-to-EU Standard** (both countries in EU, service code "11"): Only contacts required.
"""

        international_section = f"""
## International Shipping

**Enabled destinations:** {lanes_display}

International shipments require additional fields beyond domestic:
- **Recipient phone** (required)
- Recipient attention defaults to recipient name; collect/override only when the user specifies a different contact
- Shipper phone and attention name are auto-populated from configuration — do NOT ask the user for these
- **Description of goods** (max 35 chars, required for customs)
- **Commodity data** (HS tariff code, origin country, quantity, unit value per item)
- **InvoiceLineTotal** (currency + monetary value — required for US→CA)
- **Commercial invoice number** (required for invoice forms; ask user when available)
{exemptions_section}
When the user ships internationally:
- Use an international service code (07, 08, 11, 54, or 65). Domestic codes (01, 02, 03, 12, 13) are rejected.
- If the user says "standard" without qualification, ask whether they mean UPS Ground (domestic) or UPS Standard (international). Do NOT silently default.
- Never silently default ship_to_country to "US". If country is missing, ask the user.
{interactive_specific_guidance}{country_filter_examples}
"""
    else:
        international_section = """
## International Shipping

International shipping is not currently enabled. Set INTERNATIONAL_ENABLED_LANES=* in the
environment to enable all international destinations, or set specific lanes (e.g., US-CA,US-MX).
If a user asks about international shipping, inform them that it requires configuration by an
administrator.
"""

    # UPS MCP v2 — Additional capabilities (both modes)
    ups_v2_section = """
## UPS Pickup Scheduling

- Pickup type is fixed to on-call. Do NOT ask the user to choose pickup type.
- WORKFLOW: When user requests a pickup, call `rate_pickup` with ALL details (address, date, times, contact_name, phone_number). This displays a preview card with Confirm/Cancel buttons.
- After the user confirms via the preview card, call `schedule_pickup` with the SAME details + confirmed=true.
- Do NOT call schedule_pickup without first calling rate_pickup — the preview card is mandatory.
- Capture the PRN (Pickup Request Number) from the schedule response — needed for cancellation.
- Use `cancel_pickup` with the PRN to cancel a scheduled pickup.
- Use `get_pickup_status` to check pending pickups for the account.
- After batch execution completes with successful shipments, SUGGEST scheduling a pickup.
- Use `get_service_center_facilities` to suggest drop-off alternatives when pickup is not suitable.
- Pickup date format: YYYYMMDD. Times: HHMM (24-hour). ready_time must be before close_time.

## UPS Location Finder

- Use `find_locations` to find nearby UPS Access Points, retail stores, and service centers
- Use location_type `general` for broad drop-off searches; `access_point` or `retail` only when explicitly requested
- Default search radius: 15 miles (configurable with radius and unit_of_measure)
- Present results with address, phone, and operating hours

## Landed Cost (International)

- Use `get_landed_cost` to estimate duties, taxes, and fees for international shipments
- Required: currency_code, export_country_code, import_country_code, commodities list
- Each commodity needs at minimum: price, quantity. HS code (hs_code) recommended for accuracy
- Present per-commodity breakdown: duties, taxes, fees + total landed cost

## Paperless Customs Documents

- When a user wants to upload a customs document, call `request_document_upload` to show the upload form
- NEVER ask users for file paths or try to read files yourself
- After the user attaches a file, you will receive a [DOCUMENT_ATTACHED] message
- Then call `upload_paperless_document` with the appropriate document_type — file data is auto-loaded from the attachment
- Document type codes: "002" (commercial invoice), "003" (certificate of origin), "006" (packing list), "011" (weight certificate)
- After upload, capture the DocumentID from the response
- Use `push_document_to_shipment` to attach a document to a shipment using the tracking number
- Use `delete_paperless_document` to remove a document from UPS Forms History
- Chained workflow: request_document_upload → user attaches → upload_paperless_document → create shipment → push_document_to_shipment

## Package Tracking

- Use `track_package` to track a UPS package by tracking number.
- The tool validates that the response matches the requested tracking number.
- If mismatch detected (common in sandbox), the tool will flag it in the result.
- No data source or prior shipment is required — the user just needs a tracking number.

## Reference Data

- Use `get_political_divisions` to look up valid states/provinces for any country code
- Useful when validating user-provided international addresses
"""

    # Build contacts section if contacts are provided
    contacts_section = _build_contacts_section(contacts) if contacts else ""

    # Prior conversation section for session resume
    prior_section = ""
    if prior_conversation:
        prior_section = _build_prior_conversation_section(prior_conversation)

    return f"""You are ShipAgent, an AI shipping assistant that helps users create, rate, and manage UPS shipments from their data sources.

Current date: {current_date}

## UPS Service Codes

{service_table}
{international_section}
{ups_v2_section}
## Connected Data Source

{data_section}
{contacts_section}
{prior_section}
## Filter Generation Rules

{filter_rules_section}

## Workflow
{workflow_section}

## Safety Rules
{common_safety}{batch_safety}{safety_mode_section}
{interactive_validation_section}
## Tool Usage

{tool_usage_section}
"""
