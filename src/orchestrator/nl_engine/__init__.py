"""Natural Language Engine for parsing shipping commands.

This module provides intent parsing, filter generation, mapping
template generation, template validation, self-correction, and
elicitation using Claude's structured outputs.
"""

# Import template_validator first to avoid circular imports
# (self_correction and correction models depend on ValidationError)
from src.orchestrator.nl_engine.template_validator import (
    TemplateValidationError,
    ValidationError,
    ValidationResult,
    format_validation_errors,
    validate_field_value,
    validate_template_output,
)
from src.orchestrator.nl_engine.ups_schema import (
    UPS_PACKAGE_SCHEMA,
    UPS_SHIPMENT_SCHEMA,
    UPS_SHIPTO_SCHEMA,
    get_schema_for_path,
)
from src.orchestrator.nl_engine.elicitation import (
    ELICITATION_TEMPLATES,
    create_elicitation_context,
    create_elicitation_question,
    handle_elicitation_response,
    needs_elicitation,
)
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
from src.orchestrator.nl_engine.mapping_generator import (
    UPS_REQUIRED_FIELDS,
    compute_schema_hash,
    generate_mapping_template,
    render_template,
    suggest_mappings,
)
from src.orchestrator.nl_engine.self_correction import (
    extract_template_from_response,
    format_errors_for_llm,
    format_user_feedback,
    self_correction_loop,
)
from src.orchestrator.models.correction import MaxCorrectionsExceeded
from src.orchestrator.models.mapping import MappingGenerationError

__all__ = [
    # Elicitation
    "ELICITATION_TEMPLATES",
    "create_elicitation_question",
    "handle_elicitation_response",
    "needs_elicitation",
    "create_elicitation_context",
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
    # Self-correction
    "self_correction_loop",
    "format_errors_for_llm",
    "extract_template_from_response",
    "format_user_feedback",
    "MaxCorrectionsExceeded",
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
