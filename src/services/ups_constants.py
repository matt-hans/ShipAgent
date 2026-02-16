"""Canonical UPS payload constants.

Single source of truth for all UPS payload defaults, field limits,
packaging codes, and shipping lane definitions. All payload-building
modules import from here instead of using inline magic numbers.

Follows the same pattern as ups_service_codes.py (Enum + parallel
lookups + frozenset).
"""

from enum import Enum


# ---------------------------------------------------------------------------
# Carrier identity
# ---------------------------------------------------------------------------

UPS_CARRIER_NAME = "UPS"

# ---------------------------------------------------------------------------
# UPS field limits
# ---------------------------------------------------------------------------

UPS_ADDRESS_MAX_LEN = 35
UPS_PHONE_MAX_DIGITS = 15
UPS_PHONE_MIN_DIGITS = 7
UPS_REFERENCE_MAX_LEN = 35


# ---------------------------------------------------------------------------
# Packaging codes
# ---------------------------------------------------------------------------


class PackagingCode(str, Enum):
    """UPS packaging type codes.

    These codes correspond to UPS API PackagingType identifiers.
    """

    LETTER = "01"
    CUSTOMER_SUPPLIED = "02"
    TUBE = "03"
    PAK = "04"
    EXPRESS_BOX = "21"
    BOX_25KG = "24"
    BOX_10KG = "25"
    PALLET = "30"
    SMALL_EXPRESS_BOX = "2a"
    MEDIUM_EXPRESS_BOX = "2b"
    LARGE_EXPRESS_BOX = "2c"
    FLATS = "56"
    PARCELS = "57"
    BPM = "58"
    FIRST_CLASS = "59"
    PRIORITY = "60"
    MACHINEABLES = "61"
    IRREGULARS = "62"
    PARCEL_POST = "63"
    BPM_PARCEL = "64"
    MEDIA_MAIL = "65"
    BPM_FLAT = "66"
    STANDARD_FLAT = "67"


DEFAULT_PACKAGING_CODE = PackagingCode.CUSTOMER_SUPPLIED

# Alias mapping: human-readable names → PackagingCode enum values
PACKAGING_ALIASES: dict[str, PackagingCode] = {
    "ups letter": PackagingCode.LETTER,
    "letter": PackagingCode.LETTER,
    "customer supplied package": PackagingCode.CUSTOMER_SUPPLIED,
    "customer supplied": PackagingCode.CUSTOMER_SUPPLIED,
    "custom": PackagingCode.CUSTOMER_SUPPLIED,
    "tube": PackagingCode.TUBE,
    "ups tube": PackagingCode.TUBE,
    "pak": PackagingCode.PAK,
    "ups pak": PackagingCode.PAK,
    "ups express box": PackagingCode.EXPRESS_BOX,
    "express box": PackagingCode.EXPRESS_BOX,
    "25kg box": PackagingCode.BOX_25KG,
    "ups 25kg box": PackagingCode.BOX_25KG,
    "10kg box": PackagingCode.BOX_10KG,
    "ups 10kg box": PackagingCode.BOX_10KG,
    "pallet": PackagingCode.PALLET,
    "small express box": PackagingCode.SMALL_EXPRESS_BOX,
    "ups small express box": PackagingCode.SMALL_EXPRESS_BOX,
    "medium express box": PackagingCode.MEDIUM_EXPRESS_BOX,
    "ups medium express box": PackagingCode.MEDIUM_EXPRESS_BOX,
    "large express box": PackagingCode.LARGE_EXPRESS_BOX,
    "ups large express box": PackagingCode.LARGE_EXPRESS_BOX,
    "flats": PackagingCode.FLATS,
    "parcels": PackagingCode.PARCELS,
    "bpm": PackagingCode.BPM,
    "first class": PackagingCode.FIRST_CLASS,
    "priority": PackagingCode.PRIORITY,
    "machineables": PackagingCode.MACHINEABLES,
    "irregulars": PackagingCode.IRREGULARS,
    "parcel post": PackagingCode.PARCEL_POST,
    "bpm parcel": PackagingCode.BPM_PARCEL,
    "media mail": PackagingCode.MEDIA_MAIL,
    "bpm flat": PackagingCode.BPM_FLAT,
    "standard flat": PackagingCode.STANDARD_FLAT,
}


# ---------------------------------------------------------------------------
# Weight / dimension defaults
# ---------------------------------------------------------------------------

UPS_WEIGHT_UNIT = "LBS"
UPS_DIMENSION_UNIT = "IN"
GRAMS_PER_LB = 453.592
DEFAULT_PACKAGE_WEIGHT_LBS = 1.0


# ---------------------------------------------------------------------------
# Country defaults
# ---------------------------------------------------------------------------

DEFAULT_ORIGIN_COUNTRY = "US"


# ---------------------------------------------------------------------------
# International forms
# ---------------------------------------------------------------------------

DEFAULT_FORM_TYPE = "01"
DEFAULT_CURRENCY_CODE = "USD"
DEFAULT_REASON_FOR_EXPORT = "SALE"


# ---------------------------------------------------------------------------
# Label specification
# ---------------------------------------------------------------------------

DEFAULT_LABEL_FORMAT = "PDF"
DEFAULT_LABEL_HEIGHT = "6"
DEFAULT_LABEL_WIDTH = "4"


# ---------------------------------------------------------------------------
# International form types
# ---------------------------------------------------------------------------

INTERNATIONAL_FORM_TYPES: dict[str, str] = {
    "01": "Invoice",
    "03": "CO (Certificate of Origin)",
    "04": "NAFTA/USMCA Certificate of Origin",
    "05": "Partial Invoice",
    "06": "Packinglist",
    "07": "Customer Generated Forms",
    "08": "Air Freight Packing List",
    "09": "CN22 Form",
    "10": "UPS Premium Care Form",
    "11": "EEI (Electronic Export Information)",
}

REASON_FOR_EXPORT_VALUES: frozenset[str] = frozenset({
    "SALE", "GIFT", "SAMPLE", "RETURN", "REPAIR", "INTERCOMPANYDATA",
})

# EU member states (post-Brexit, 27 members — excludes GB, NO, CH)
EU_MEMBER_STATES: frozenset[str] = frozenset({
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
    "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL",
    "PL", "PT", "RO", "SK", "SI", "ES", "SE",
})

# Form types that require Product[] (commodity-level data)
FORMS_REQUIRING_PRODUCTS: frozenset[str] = frozenset({
    "01", "03", "04", "05", "06", "08", "11",
})
