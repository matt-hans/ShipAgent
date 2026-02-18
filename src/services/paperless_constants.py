"""UPS Paperless file-format constants and normalization helpers."""

from __future__ import annotations

# Canonical formats from UPS Paperless OpenAPI (Paperless.yaml).
UPS_PAPERLESS_CANONICAL_FORMATS: tuple[str, ...] = (
    "bmp",
    "doc",
    "docx",
    "gif",
    "jpg",
    "pdf",
    "png",
    "rtf",
    "tif",
    "txt",
    "xls",
    "xlsx",
)

# Convenience aliases accepted by UI/backend, normalized before UPS call.
UPS_PAPERLESS_FORMAT_ALIASES: dict[str, str] = {
    "jpeg": "jpg",
    "tiff": "tif",
}

UPS_PAPERLESS_ALLOWED_EXTENSIONS: frozenset[str] = frozenset({
    *UPS_PAPERLESS_CANONICAL_FORMATS,
    *UPS_PAPERLESS_FORMAT_ALIASES.keys(),
})

# Use in upload UI accept attr + client-side validation.
UPS_PAPERLESS_UI_ACCEPTED_FORMATS: tuple[str, ...] = (
    *UPS_PAPERLESS_CANONICAL_FORMATS,
    *tuple(sorted(UPS_PAPERLESS_FORMAT_ALIASES.keys())),
)


def normalize_paperless_extension(file_extension: str) -> str | None:
    """Normalize a file extension to UPS canonical format.

    Args:
        file_extension: Extension with or without a leading dot.

    Returns:
        Canonical UPS extension (e.g. ``jpg``), or None if unsupported.
    """
    ext = file_extension.strip().lower().lstrip(".")
    if not ext:
        return None
    if ext in UPS_PAPERLESS_CANONICAL_FORMATS:
        return ext
    return UPS_PAPERLESS_FORMAT_ALIASES.get(ext)
