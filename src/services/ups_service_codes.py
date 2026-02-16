"""Canonical UPS service code definitions.

Single source of truth for all UPS service code enums, aliases,
display names, and resolver functions. All other modules import
from here instead of maintaining their own copies.
"""

from enum import Enum


class ServiceCode(str, Enum):
    """UPS service codes for shipping services.

    These codes correspond to UPS API service type identifiers.
    """

    NEXT_DAY_AIR = "01"
    SECOND_DAY_AIR = "02"
    GROUND = "03"
    WORLDWIDE_EXPRESS = "07"
    WORLDWIDE_EXPEDITED = "08"
    UPS_STANDARD = "11"
    THREE_DAY_SELECT = "12"
    NEXT_DAY_AIR_SAVER = "13"
    NEXT_DAY_AIR_EARLY = "14"
    WORLDWIDE_EXPRESS_PLUS = "54"
    SECOND_DAY_AIR_AM = "59"
    WORLDWIDE_SAVER = "65"


# ---------------------------------------------------------------------------
# Alias mapping — maps user-friendly terms to ServiceCode enum values
# ---------------------------------------------------------------------------

SERVICE_ALIASES: dict[str, ServiceCode] = {
    # Ground
    "ground": ServiceCode.GROUND,
    "ups ground": ServiceCode.GROUND,
    # Next Day Air
    "overnight": ServiceCode.NEXT_DAY_AIR,
    "next day": ServiceCode.NEXT_DAY_AIR,
    "next day air": ServiceCode.NEXT_DAY_AIR,
    "ups next day air": ServiceCode.NEXT_DAY_AIR,
    "nda": ServiceCode.NEXT_DAY_AIR,
    "express": ServiceCode.NEXT_DAY_AIR,
    # Second Day Air
    "2-day": ServiceCode.SECOND_DAY_AIR,
    "2 day": ServiceCode.SECOND_DAY_AIR,
    "two day": ServiceCode.SECOND_DAY_AIR,
    "2nd day air": ServiceCode.SECOND_DAY_AIR,
    "second day air": ServiceCode.SECOND_DAY_AIR,
    "ups 2nd day air": ServiceCode.SECOND_DAY_AIR,
    # Three Day Select
    "3-day": ServiceCode.THREE_DAY_SELECT,
    "3 day": ServiceCode.THREE_DAY_SELECT,
    "three day": ServiceCode.THREE_DAY_SELECT,
    "3 day select": ServiceCode.THREE_DAY_SELECT,
    "three day select": ServiceCode.THREE_DAY_SELECT,
    "ups 3 day select": ServiceCode.THREE_DAY_SELECT,
    # Next Day Air Saver
    "saver": ServiceCode.NEXT_DAY_AIR_SAVER,
    "next day air saver": ServiceCode.NEXT_DAY_AIR_SAVER,
    "ups next day air saver": ServiceCode.NEXT_DAY_AIR_SAVER,
    "nda saver": ServiceCode.NEXT_DAY_AIR_SAVER,
    # Next Day Air Early
    "next day air early": ServiceCode.NEXT_DAY_AIR_EARLY,
    "ups next day air early": ServiceCode.NEXT_DAY_AIR_EARLY,
    "next day air early am": ServiceCode.NEXT_DAY_AIR_EARLY,
    "early am": ServiceCode.NEXT_DAY_AIR_EARLY,
    # Second Day Air A.M.
    "2nd day air am": ServiceCode.SECOND_DAY_AIR_AM,
    "ups 2nd day air am": ServiceCode.SECOND_DAY_AIR_AM,
    "2 day am": ServiceCode.SECOND_DAY_AIR_AM,
    "second day air am": ServiceCode.SECOND_DAY_AIR_AM,
    # UPS Standard (primarily Canada/Mexico)
    "ups standard": ServiceCode.UPS_STANDARD,
    # NOTE: bare "standard" is intentionally NOT aliased — it's ambiguous
    # ("standard shipping" = Ground vs "UPS Standard" = code 11 international).
    # Users must say "ups standard" to get code 11.
    # Worldwide Express
    "worldwide express": ServiceCode.WORLDWIDE_EXPRESS,
    "ups worldwide express": ServiceCode.WORLDWIDE_EXPRESS,
    "international express": ServiceCode.WORLDWIDE_EXPRESS,
    # Worldwide Expedited
    "worldwide expedited": ServiceCode.WORLDWIDE_EXPEDITED,
    "ups worldwide expedited": ServiceCode.WORLDWIDE_EXPEDITED,
    # Worldwide Express Plus
    "worldwide express plus": ServiceCode.WORLDWIDE_EXPRESS_PLUS,
    "ups worldwide express plus": ServiceCode.WORLDWIDE_EXPRESS_PLUS,
    "express plus": ServiceCode.WORLDWIDE_EXPRESS_PLUS,
    # Worldwide Saver
    "worldwide saver": ServiceCode.WORLDWIDE_SAVER,
    "ups worldwide saver": ServiceCode.WORLDWIDE_SAVER,
    # International Standard (alias for UPS Standard code 11)
    "international standard": ServiceCode.UPS_STANDARD,
}

# Reverse mapping: code value → ServiceCode enum member
CODE_TO_SERVICE: dict[str, ServiceCode] = {code.value: code for code in ServiceCode}

# Display names: code value → human-readable name
SERVICE_CODE_NAMES: dict[str, str] = {
    "01": "UPS Next Day Air",
    "02": "UPS 2nd Day Air",
    "03": "UPS Ground",
    "07": "UPS Worldwide Express",
    "08": "UPS Worldwide Expedited",
    "11": "UPS Standard",
    "12": "UPS 3 Day Select",
    "13": "UPS Next Day Air Saver",
    "14": "UPS Next Day Air Early",
    "54": "UPS Worldwide Express Plus",
    "59": "UPS 2nd Day Air A.M.",
    "65": "UPS Worldwide Saver",
}

# Auto-derived string-value alias map (for column_mapping compatibility)
SERVICE_NAME_TO_CODE: dict[str, str] = {k: v.value for k, v in SERVICE_ALIASES.items()}

# International vs domestic service sets
SUPPORTED_INTERNATIONAL_SERVICES: frozenset[str] = frozenset({
    "07",  # UPS Worldwide Express
    "08",  # UPS Worldwide Expedited
    "11",  # UPS Standard (CA/MX)
    "54",  # UPS Worldwide Express Plus
    "65",  # UPS Worldwide Saver
})

DOMESTIC_ONLY_SERVICES: frozenset[str] = frozenset({
    "01",  # Next Day Air
    "02",  # 2nd Day Air
    "03",  # Ground
    "12",  # 3 Day Select
    "13",  # Next Day Air Saver
    "14",  # Next Day Air Early
})


# Domestic → international equivalent mapping for auto-upgrade
DOMESTIC_TO_INTERNATIONAL: dict[str, str] = {
    "03": "11",  # Ground → UPS Standard
    "01": "07",  # Next Day Air → Worldwide Express
    "02": "08",  # 2nd Day Air → Worldwide Expedited
    "12": "65",  # 3 Day Select → Worldwide Saver
    "13": "65",  # Next Day Air Saver → Worldwide Saver
    "14": "54",  # Next Day Air Early → Worldwide Express Plus
}


def upgrade_to_international(
    service_code: str, origin: str, destination: str,
) -> str:
    """Auto-upgrade a domestic service code to its international equivalent.

    When the destination is international and the service code is domestic-only,
    maps it to the closest international service. Returns the original code if
    already international or if the shipment is domestic.

    Args:
        service_code: UPS service code (e.g., "03").
        origin: Origin country code (e.g., "US").
        destination: Destination country code (e.g., "GB").

    Returns:
        International service code if upgrade needed, otherwise original.
    """
    if origin.upper() == destination.upper():
        return service_code
    if service_code in DOMESTIC_TO_INTERNATIONAL:
        return DOMESTIC_TO_INTERNATIONAL[service_code]
    return service_code


def resolve_service_code(raw_value: str | None, default: str = "03") -> str:
    """Resolve a service value to a UPS numeric service code.

    Accepts either a numeric code directly (e.g. "03") or a
    human-readable name (e.g. "Ground", "Next Day Air").

    Args:
        raw_value: Service code or name string.
        default: Default service code ("03" = Ground).

    Returns:
        UPS service code string.
    """
    if not raw_value:
        return default

    stripped = raw_value.strip()

    # Already a valid numeric code
    if stripped.isdigit():
        return stripped

    # Lookup by lowercase in the alias map
    matched = SERVICE_ALIASES.get(stripped.lower())
    if matched is not None:
        return matched.value

    return default


def translate_service_name(name: str) -> str:
    """Translate a human-readable service name to a UPS service code.

    Case-insensitive lookup. Returns the original value if already a
    numeric code or if no match is found.

    Args:
        name: Service name string (e.g., "Ground", "Next Day Air").

    Returns:
        UPS service code string (e.g., "03", "01").
    """
    return resolve_service_code(name)
