"""Error formatting and grouping utilities.

This module provides:
- ShipAgentError exception class for application errors
- Error formatting for user display
- Error grouping to combine duplicates across rows
"""

from dataclasses import dataclass, field

from src.errors.registry import get_error


@dataclass
class ShipAgentError(Exception):
    """Application error with code, message, and context.

    Attributes:
        code: Error code in E-XXXX format.
        message: Human-readable error message.
        remediation: Action user should take to resolve.
        rows: List of affected row numbers.
        column: Affected column name, if applicable.
        is_retryable: Whether the operation can be retried without user action.
        details: Additional context dictionary.
    """

    code: str
    message: str
    remediation: str
    rows: list[int] = field(default_factory=list)  # Affected row numbers
    column: str | None = None  # Affected column name
    is_retryable: bool = False
    details: dict = field(default_factory=dict)  # Additional context

    def __str__(self) -> str:
        """Return string representation of the error."""
        return f"{self.code}: {self.message}"

    @classmethod
    def from_code(cls, code: str, **kwargs: object) -> "ShipAgentError":
        """Create error from registry code with context substitution.

        Args:
            code: Error code in E-XXXX format.
            **kwargs: Context values for message template substitution.
                Special keys 'rows', 'column', 'details' are used for
                ShipAgentError fields rather than message substitution.

        Returns:
            ShipAgentError instance with formatted message.
        """
        error_def = get_error(code)
        if not error_def:
            return cls(
                code=code,
                message=f"Unknown error: {code}",
                remediation="Contact support.",
                rows=kwargs.get("rows", []),  # type: ignore[arg-type]
                column=kwargs.get("column"),  # type: ignore[arg-type]
                details=kwargs.get("details", {}),  # type: ignore[arg-type]
            )

        # Format message with provided context
        message = error_def.message_template
        try:
            # Filter out special keys that shouldn't be in template
            # Note: 'column' is allowed in template since it's commonly used in messages
            template_kwargs = {
                k: v for k, v in kwargs.items() if k not in ("rows", "details")
            }
            message = message.format(**template_kwargs)
        except KeyError:
            # Keep template if some placeholders are missing
            pass

        # Extract special fields from kwargs
        rows = kwargs.get("rows", [])
        if not isinstance(rows, list):
            rows = []
        column = kwargs.get("column")
        if not isinstance(column, str) and column is not None:
            column = None
        details = kwargs.get("details", {})
        if not isinstance(details, dict):
            details = {}

        return cls(
            code=error_def.code,
            message=message,
            remediation=error_def.remediation,
            is_retryable=error_def.is_retryable,
            rows=rows,
            column=column,
            details=details,
        )


def format_error(error: ShipAgentError, include_remediation: bool = True) -> str:
    """Format error for display to user.

    Args:
        error: The ShipAgentError to format.
        include_remediation: Whether to include remediation steps.

    Returns:
        Multi-line formatted string suitable for user display.
    """
    lines = [f"{error.code}: {error.message}"]

    # Add row/column context
    if error.rows:
        if len(error.rows) == 1:
            lines.append(f"  Location: Row {error.rows[0]}")
        else:
            rows_str = ", ".join(str(r) for r in error.rows[:10])
            if len(error.rows) > 10:
                rows_str += f" (and {len(error.rows) - 10} more)"
            lines.append(f"  Affected rows: {rows_str}")

    if error.column:
        lines.append(f"  Column: {error.column}")

    # Add remediation
    if include_remediation:
        lines.append(f"  Action: {error.remediation}")

    return "\n".join(lines)


def group_errors(errors: list[ShipAgentError]) -> list[ShipAgentError]:
    """Group errors by code and message, combining row numbers.

    Same errors appearing on multiple rows are combined into a single
    error with all affected row numbers listed.

    Example:
        5 identical "Invalid ZIP" errors on rows 1,2,3,4,5
        -> 1 error with rows=[1,2,3,4,5]

    Args:
        errors: List of ShipAgentError objects to group.

    Returns:
        List of grouped ShipAgentError objects with combined rows.
    """
    groups: dict[str, ShipAgentError] = {}

    for error in errors:
        # Create a key from code and message (not rows)
        key = f"{error.code}|{error.message}|{error.column or ''}"

        if key in groups:
            # Add rows to existing group
            groups[key].rows.extend(error.rows)
        else:
            # Create new group
            groups[key] = ShipAgentError(
                code=error.code,
                message=error.message,
                remediation=error.remediation,
                rows=list(error.rows),  # Copy to avoid mutation
                column=error.column,
                is_retryable=error.is_retryable,
                details=error.details.copy(),
            )

    # Sort rows within each group and return as list
    result = list(groups.values())
    for error in result:
        error.rows = sorted(set(error.rows))  # Dedupe and sort

    return result


def format_error_summary(errors: list[ShipAgentError]) -> str:
    """Format a list of errors for display, grouping duplicates.

    Args:
        errors: List of ShipAgentError objects.

    Returns:
        User-friendly summary suitable for UI display.
    """
    if not errors:
        return "No errors."

    grouped = group_errors(errors)

    if len(grouped) == 1:
        return format_error(grouped[0])

    lines = [f"{len(grouped)} error type(s) found:\n"]
    for i, error in enumerate(grouped, 1):
        lines.append(f"{i}. {format_error(error)}")
        lines.append("")  # Blank line between errors

    return "\n".join(lines)
