"""Mapping template generator for source-to-UPS transformations.

This module generates Jinja2 mapping templates that transform source data
(CSV/Excel columns) into valid UPS API payloads. It provides:

- UPS_REQUIRED_FIELDS: Key fields for MVP shipping payloads
- suggest_mappings: LLM-powered column mapping suggestions
- generate_mapping_template: Create Jinja2 template from user mappings
- compute_schema_hash: Deterministic hash of schema for template matching
- render_template: Apply template to row data
"""

import hashlib
import json
import re
from typing import Any, Optional

from src.orchestrator.filters.logistics import get_logistics_environment
from src.orchestrator.models.filter import ColumnInfo
from src.orchestrator.models.mapping import (
    FieldMapping,
    MappingGenerationError,
    MappingTemplate,
    UPSTargetField,
)


# Key UPS fields for MVP shipping payloads
# Based on UPS Shipping API ShipmentRequest schema
UPS_REQUIRED_FIELDS: list[UPSTargetField] = [
    UPSTargetField(
        path="ShipTo.Name",
        type="string",
        required=True,
        max_length=35,
        description="Recipient name on shipping label",
    ),
    UPSTargetField(
        path="ShipTo.Address.AddressLine",
        type="array",
        required=True,
        max_length=35,
        description="Street address lines (up to 3, max 35 chars each)",
    ),
    UPSTargetField(
        path="ShipTo.Address.City",
        type="string",
        required=True,
        max_length=30,
        description="City name",
    ),
    UPSTargetField(
        path="ShipTo.Address.StateProvinceCode",
        type="string",
        required=True,
        max_length=5,
        description="State/Province code (required for US/CA/PR)",
    ),
    UPSTargetField(
        path="ShipTo.Address.PostalCode",
        type="string",
        required=True,
        max_length=9,
        description="Postal/ZIP code (required for US/CA/PR)",
    ),
    UPSTargetField(
        path="ShipTo.Address.CountryCode",
        type="string",
        required=True,
        max_length=2,
        description="Two-letter country code (e.g., US, CA)",
    ),
    UPSTargetField(
        path="ShipTo.Phone.Number",
        type="string",
        required=False,
        max_length=15,
        description="Recipient phone number",
    ),
    UPSTargetField(
        path="Package.PackageWeight.Weight",
        type="number",
        required=True,
        max_length=None,
        description="Package weight in specified unit",
    ),
]


def compute_schema_hash(columns: list[str]) -> str:
    """Compute deterministic hash of column names for template matching.

    The hash is order-independent to ensure the same columns always
    produce the same hash regardless of column order.

    Args:
        columns: List of column names from source data.

    Returns:
        First 16 characters of SHA256 hash.

    Examples:
        >>> compute_schema_hash(["name", "city", "state"])
        'a1b2c3d4e5f6g7h8'
        >>> compute_schema_hash(["state", "city", "name"])  # Same hash
        'a1b2c3d4e5f6g7h8'
    """
    # Sort columns for order-independence
    sorted_columns = sorted(columns)
    # JSON encode for consistent serialization
    json_str = json.dumps(sorted_columns, sort_keys=True)
    # SHA256 hash
    hash_bytes = hashlib.sha256(json_str.encode()).hexdigest()
    # Return first 16 characters
    return hash_bytes[:16]


def _path_to_nested_dict(path: str, value: str) -> dict[str, Any]:
    """Convert a dot-notation path to nested dict structure.

    Args:
        path: Dot-notation path (e.g., "ShipTo.Address.City").
        value: Jinja2 expression for the value.

    Returns:
        Nested dict structure.

    Example:
        >>> _path_to_nested_dict("ShipTo.Address.City", "{{ city }}")
        {"ShipTo": {"Address": {"City": "{{ city }}"}}}
    """
    parts = path.split(".")
    result: dict[str, Any] = {}
    current = result

    for i, part in enumerate(parts[:-1]):
        current[part] = {}
        current = current[part]

    current[parts[-1]] = value
    return result


def _merge_nested_dicts(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    """Deep merge two nested dictionaries.

    Args:
        base: Base dictionary.
        update: Dictionary to merge in.

    Returns:
        Merged dictionary (modifies base in place and returns it).
    """
    for key, value in update.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _merge_nested_dicts(base[key], value)
        else:
            base[key] = value
    return base


def _build_jinja_expression(mapping: FieldMapping) -> str:
    """Build Jinja2 expression from field mapping.

    Args:
        mapping: Field mapping configuration.

    Returns:
        Jinja2 expression string.

    Note:
        default_value is applied BEFORE transformation so that None/empty
        values get replaced before the transformation filter runs. This
        prevents errors like to_ups_phone receiving None.

    Examples:
        >>> _build_jinja_expression(FieldMapping(source_column="name", target_path="ShipTo.Name"))
        '{{ name }}'
        >>> _build_jinja_expression(FieldMapping(
        ...     source_column="name",
        ...     target_path="ShipTo.Name",
        ...     transformation="truncate_address(35)"
        ... ))
        '{{ name | truncate_address(35) }}'
    """
    expr = f"{{{{ {mapping.source_column}"

    # Apply default_value FIRST so None gets replaced before transformation
    if mapping.default_value is not None:
        # Escape string defaults
        if isinstance(mapping.default_value, str):
            default_escaped = mapping.default_value.replace("'", "\\'")
            expr += f" | default_value('{default_escaped}')"
        else:
            expr += f" | default_value({mapping.default_value})"

    # Apply transformation AFTER default_value
    if mapping.transformation:
        expr += f" | {mapping.transformation}"

    expr += " }}"
    return expr


def generate_mapping_template(
    source_schema: list[ColumnInfo],
    user_mappings: list[FieldMapping],
    template_name: str = "default",
) -> MappingTemplate:
    """Generate a Jinja2 mapping template from user-provided mappings.

    Creates a complete MappingTemplate with a compiled Jinja2 template
    string that transforms source row data to UPS payload format.

    Args:
        source_schema: List of column info from source data.
        user_mappings: List of field mappings provided by user.
        template_name: Name for the template (default: "default").

    Returns:
        MappingTemplate with jinja_template populated.

    Raises:
        MappingGenerationError: If template compilation fails.

    Example:
        >>> schema = [ColumnInfo(name="name", type="string")]
        >>> mappings = [FieldMapping(source_column="name", target_path="ShipTo.Name")]
        >>> template = generate_mapping_template(schema, mappings, "my_template")
        >>> print(template.jinja_template)
        {
          "ShipTo": {
            "Name": "{{ name }}"
          }
        }
    """
    # Compute schema hash from column names
    column_names = [col.name for col in source_schema]
    schema_hash = compute_schema_hash(column_names)

    # Validate source columns exist in schema
    schema_columns = set(column_names)
    for mapping in user_mappings:
        if mapping.source_column not in schema_columns:
            raise MappingGenerationError(
                f"Source column '{mapping.source_column}' not found in schema. "
                f"Available columns: {', '.join(sorted(schema_columns))}",
                source_column=mapping.source_column,
                target_path=mapping.target_path,
            )

    # Build template structure
    template_dict: dict[str, Any] = {}

    for mapping in user_mappings:
        jinja_expr = _build_jinja_expression(mapping)
        nested = _path_to_nested_dict(mapping.target_path, jinja_expr)
        _merge_nested_dicts(template_dict, nested)

    # Convert to JSON string with proper formatting
    # Use a custom encoder to preserve Jinja2 expressions
    template_json = json.dumps(template_dict, indent=2)

    # Validate that template compiles in the logistics environment
    env = get_logistics_environment()
    try:
        env.from_string(template_json)
    except Exception as e:
        raise MappingGenerationError(
            f"Failed to compile Jinja2 template: {e}",
        ) from e

    # Identify missing required fields
    mapped_paths = {m.target_path for m in user_mappings}
    missing_required = [
        field.path
        for field in UPS_REQUIRED_FIELDS
        if field.required and field.path not in mapped_paths
    ]

    return MappingTemplate(
        name=template_name,
        source_schema_hash=schema_hash,
        mappings=user_mappings,
        missing_required=missing_required,
        jinja_template=template_json,
    )


def render_template(template: MappingTemplate, row_data: dict[str, Any]) -> dict[str, Any]:
    """Render a mapping template with row data.

    Applies the Jinja2 template to transform source row data
    into UPS payload format.

    Args:
        template: MappingTemplate with jinja_template populated.
        row_data: Dictionary of column name -> value from source row.

    Returns:
        Rendered dictionary ready for UPS API payload.

    Raises:
        MappingGenerationError: If template rendering fails.

    Example:
        >>> template = MappingTemplate(
        ...     name="test",
        ...     source_schema_hash="abc123",
        ...     jinja_template='{"ShipTo": {"Name": "{{ name }}"}}',
        ... )
        >>> render_template(template, {"name": "John Doe"})
        {"ShipTo": {"Name": "John Doe"}}
    """
    if not template.jinja_template:
        raise MappingGenerationError("Template has no jinja_template set")

    env = get_logistics_environment()

    try:
        jinja_template = env.from_string(template.jinja_template)
        rendered_str = jinja_template.render(**row_data)
        result = json.loads(rendered_str)
        return result
    except json.JSONDecodeError as e:
        raise MappingGenerationError(
            f"Rendered template is not valid JSON: {e}"
        ) from e
    except Exception as e:
        raise MappingGenerationError(
            f"Failed to render template: {e}"
        ) from e


async def suggest_mappings(
    source_columns: list[str],
    example_row: Optional[dict[str, Any]] = None,
) -> list[FieldMapping]:
    """Use Claude to suggest column mappings (requires confirmation).

    This function uses Claude's structured outputs to suggest likely
    mappings from source columns to UPS fields. Per CONTEXT.md Decision 2,
    these are SUGGESTIONS ONLY - users must confirm before use.

    Args:
        source_columns: List of column names from source data.
        example_row: Optional example row data for context.

    Returns:
        List of suggested FieldMapping objects.

    Note:
        This function requires ANTHROPIC_API_KEY environment variable.
        If not set, returns an empty list.
    """
    import os

    from anthropic import Anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return []

    client = Anthropic(api_key=api_key)

    # Build system prompt with available UPS fields
    ups_fields_desc = "\n".join(
        f"- {f.path}: {f.description} (max {f.max_length} chars, {'required' if f.required else 'optional'})"
        for f in UPS_REQUIRED_FIELDS
    )

    system_prompt = f"""You are a shipping data mapping assistant. Your job is to suggest
likely mappings from source data columns to UPS shipping fields.

Available UPS target fields:
{ups_fields_desc}

IMPORTANT: These are SUGGESTIONS ONLY. Users must confirm mappings before use.
Do not auto-apply without user confirmation.

For each source column, suggest the most likely UPS target field it maps to.
Consider column names, data types, and any example values provided.
If a column doesn't clearly map to a UPS field, do not include it.

Also suggest appropriate transformations:
- truncate_address(35) for address lines
- format_us_zip for postal codes
- to_ups_phone for phone numbers
- split_name('first') or split_name('last') for name fields"""

    # Build user message
    user_msg = f"Source columns: {', '.join(source_columns)}"
    if example_row:
        user_msg += f"\n\nExample row data:\n{json.dumps(example_row, indent=2)}"

    # Define the mapping suggestion tool
    tools = [
        {
            "name": "suggest_column_mappings",
            "description": "Suggest mappings from source columns to UPS fields",
            "input_schema": {
                "type": "object",
                "properties": {
                    "mappings": {
                        "type": "array",
                        "description": "List of suggested column mappings",
                        "items": {
                            "type": "object",
                            "properties": {
                                "source_column": {
                                    "type": "string",
                                    "description": "Column name from source data",
                                },
                                "target_path": {
                                    "type": "string",
                                    "description": "UPS field path (e.g., ShipTo.Name)",
                                },
                                "transformation": {
                                    "type": "string",
                                    "description": "Optional Jinja2 filter (e.g., truncate_address(35))",
                                },
                                "confidence": {
                                    "type": "string",
                                    "enum": ["high", "medium", "low"],
                                    "description": "Confidence in this mapping suggestion",
                                },
                            },
                            "required": ["source_column", "target_path"],
                        },
                    },
                },
                "required": ["mappings"],
            },
        }
    ]

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=system_prompt,
        tools=tools,
        tool_choice={"type": "tool", "name": "suggest_column_mappings"},
        messages=[{"role": "user", "content": user_msg}],
    )

    # Extract mappings from tool use response
    suggestions: list[FieldMapping] = []

    for block in response.content:
        if block.type == "tool_use" and block.name == "suggest_column_mappings":
            mapping_data = block.input.get("mappings", [])
            for m in mapping_data:
                suggestions.append(
                    FieldMapping(
                        source_column=m["source_column"],
                        target_path=m["target_path"],
                        transformation=m.get("transformation"),
                    )
                )

    return suggestions
