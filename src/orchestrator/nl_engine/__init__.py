"""Natural Language Engine for parsing shipping commands.

This module provides intent parsing, filter generation, mapping
template generation, and template validation using Claude's
structured outputs.
"""

from src.orchestrator.nl_engine.filter_generator import (
    FilterGenerationError,
    generate_filter,
    validate_sql_syntax,
)
from src.orchestrator.nl_engine.intent_parser import (
    IntentParseError,
    parse_intent,
    resolve_service_code,
)
from src.orchestrator.nl_engine.template_validator import (
    TemplateValidationError,
    ValidationError,
    ValidationResult,
    format_validation_errors,
    validate_field_value,
    validate_template_output,
)
from src.orchestrator.nl_engine.mapping_generator import (
    UPS_REQUIRED_FIELDS,
    compute_schema_hash,
    generate_mapping_template,
    render_template,
    suggest_mappings,
)
from src.orchestrator.nl_engine.ups_schema import (
    UPS_PACKAGE_SCHEMA,
    UPS_SHIPMENT_SCHEMA,
    UPS_SHIPTO_SCHEMA,
    get_schema_for_path,
)
from src.orchestrator.models.mapping import MappingGenerationError

__all__ = [
    # Intent parsing
    "parse_intent",
    "resolve_service_code",
    "IntentParseError",
    # Filter generation
    "generate_filter",
    "validate_sql_syntax",
    "FilterGenerationError",
    # Template validation
    "validate_template_output",
    "validate_field_value",
    "format_validation_errors",
    "ValidationResult",
    "ValidationError",
    "TemplateValidationError",
    # UPS Schemas
    "UPS_SHIPTO_SCHEMA",
    "UPS_PACKAGE_SCHEMA",
    "UPS_SHIPMENT_SCHEMA",
    "get_schema_for_path",
    # Mapping generation
    "generate_mapping_template",
    "suggest_mappings",
    "compute_schema_hash",
    "render_template",
    "UPS_REQUIRED_FIELDS",
    "MappingGenerationError",
]
