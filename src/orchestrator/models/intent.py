"""Intent models for natural language shipping commands.

Re-exports canonical service code definitions. The legacy ShippingIntent,
FilterCriteria, and RowQualifier models have been removed — all intent
parsing now flows through the agent's tool parameters directly.
"""

# Re-export canonical service code definitions for backward compatibility.
# All consumers that import ServiceCode, SERVICE_ALIASES, CODE_TO_SERVICE
# from this module continue to work unchanged.
from src.services.ups_service_codes import (  # noqa: F401
    CODE_TO_SERVICE,
    SERVICE_ALIASES,
    ServiceCode,
)
