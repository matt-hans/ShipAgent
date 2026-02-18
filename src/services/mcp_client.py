"""Generic async MCP client with retry and connection lifecycle.

Reusable async context manager for communicating with any MCP server
over stdio transport. Handles connection lifecycle, JSON response parsing,
and configurable retry with exponential backoff.

Example:
    from mcp import StdioServerParameters

    params = StdioServerParameters(command="python3", args=["-m", "ups_mcp"], env={...})
    async with MCPClient(params) as client:
        result = await client.call_tool("rate_shipment", {"request_body": {...}})
"""

import asyncio
import json
import logging
import time
from typing import Any, Callable

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent
from src.services.decision_audit_service import DecisionAuditService

logger = logging.getLogger(__name__)


class MCPToolError(Exception):
    """Tool returned isError=True after retries exhausted.

    Attributes:
        tool_name: Name of the MCP tool that failed.
        error_text: Raw error text from the tool response.
    """

    def __init__(self, tool_name: str, error_text: str) -> None:
        """Initialize with tool name and error text.

        Args:
            tool_name: The MCP tool name that returned an error.
            error_text: The raw error text from the tool response.
        """
        self.tool_name = tool_name
        self.error_text = error_text
        super().__init__(f"MCP tool '{tool_name}' failed: {error_text}")


class MCPConnectionError(Exception):
    """Failed to spawn or connect to MCP server.

    Attributes:
        command: The command that failed to spawn.
        reason: Description of why the connection failed.
    """

    def __init__(self, command: str, reason: str) -> None:
        """Initialize with command and failure reason.

        Args:
            command: The command that was attempted.
            reason: Why the connection failed.
        """
        self.command = command
        self.reason = reason
        super().__init__(f"Failed to connect to MCP server '{command}': {reason}")


# Default retryable error classifier
_DEFAULT_RETRYABLE_PATTERNS = [
    "429", "503", "502", "rate limit", "timeout", "connection",
]


def _default_is_retryable(error_text: str) -> bool:
    """Check if an error is retryable using default patterns.

    Args:
        error_text: The error text to check.

    Returns:
        True if the error matches a retryable pattern.
    """
    lower = error_text.lower()
    return any(p in lower for p in _DEFAULT_RETRYABLE_PATTERNS)


async def _auto_decline_elicitation(context: Any, params: Any) -> Any:
    """Auto-decline elicitation requests from MCP servers.

    Used by programmatic MCP clients where no user is available to
    provide missing field values. The MCP server will translate
    this into an ELICITATION_DECLINED error with structured missing
    field metadata.

    Args:
        context: MCP request context (unused).
        params: Elicitation request parameters (unused).

    Returns:
        ElicitResult with action='decline'.
    """
    from mcp.types import ElicitResult

    logger.debug("Auto-declining MCP elicitation request")
    return ElicitResult(action="decline")


class MCPClient:
    """Generic async MCP client with retry logic.

    Manages the full lifecycle of an MCP server connection via stdio
    transport. Supports configurable retry with exponential backoff
    and pluggable retryable-error classifiers.

    Attributes:
        _server_params: Parameters for spawning the MCP server process.
        _max_retries: Maximum number of retry attempts per tool call.
        _base_delay: Base delay in seconds for exponential backoff.
        _is_retryable: Callback to classify errors as retryable.
    """

    def __init__(
        self,
        server_params: StdioServerParameters,
        max_retries: int = 3,
        base_delay: float = 1.0,
        is_retryable: Callable[[str], bool] | None = None,
        elicitation_callback: Any | None = None,
    ) -> None:
        """Initialize MCP client.

        Args:
            server_params: StdioServerParameters for the MCP server.
            max_retries: Max retry attempts for transient errors.
            base_delay: Base delay in seconds (doubles each retry).
            is_retryable: Optional callback to classify errors. Defaults to
                matching 429, 503, 502, rate limit, timeout, connection.
            elicitation_callback: Optional callback for MCP elicitation requests.
                When provided, ClientSession declares ElicitationCapability.
                Use ``_auto_decline_elicitation`` for programmatic clients.
        """
        self._server_params = server_params
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._is_retryable = is_retryable or _default_is_retryable
        self._elicitation_callback = elicitation_callback
        self._session: ClientSession | None = None
        self._stdio_context: Any = None
        self._session_context: Any = None
        self._retry_attempts_total = 0

    @property
    def is_connected(self) -> bool:
        """Whether the MCP session is currently connected."""
        return self._session is not None

    async def check_health(self) -> bool:
        """Lightweight health check — calls list_tools() to verify responsiveness.

        Returns False on any failure rather than raising, making it safe
        for monitoring paths.

        Returns:
            True if the connection is alive and responsive.
        """
        if self._session is None:
            return False
        try:
            await self._session.list_tools()
            return True
        except Exception:
            return False

    @property
    def retry_attempts_total(self) -> int:
        """Total number of retry sleeps performed by this client."""
        return self._retry_attempts_total

    async def __aenter__(self) -> "MCPClient":
        """Spawn MCP server and initialize session.

        Returns:
            Self with active session.

        Raises:
            MCPConnectionError: If the server fails to spawn or initialize.
        """
        await self.connect()
        return self

    async def connect(self) -> None:
        """Connect to the MCP server if not already connected.

        Creates fresh stdio/session contexts on each disconnected connect call.

        Raises:
            MCPConnectionError: If the server fails to spawn or initialize.
        """
        if self._session is not None:
            return

        try:
            # Ensure stale partial contexts are cleared before reconnect.
            await self._cleanup()
            self._stdio_context = stdio_client(self._server_params)
            read_stream, write_stream = await self._stdio_context.__aenter__()
            session_kwargs: dict[str, Any] = {}
            if self._elicitation_callback is not None:
                session_kwargs["elicitation_callback"] = self._elicitation_callback
            self._session_context = ClientSession(
                read_stream, write_stream, **session_kwargs,
            )
            self._session = await self._session_context.__aenter__()
            await self._session.initialize()
            logger.info(
                "MCP client connected to '%s'", self._server_params.command,
            )
        except Exception as e:
            # Clean up partial state on failure
            await self._cleanup()
            raise MCPConnectionError(
                command=self._server_params.command,
                reason=str(e),
            ) from e

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Shut down session and stop MCP server process.

        Args:
            exc_type: Exception type if exiting due to error.
            exc_val: Exception value if exiting due to error.
            exc_tb: Exception traceback if exiting due to error.
        """
        await self.disconnect()

    async def disconnect(self) -> None:
        """Disconnect MCP session and stop MCP server process."""
        await self._cleanup()

    async def _cleanup(self) -> None:
        """Clean up session and stdio contexts."""
        if self._session_context is not None:
            try:
                await self._session_context.__aexit__(None, None, None)
            except Exception:
                pass
            self._session_context = None
            self._session = None

        if self._stdio_context is not None:
            try:
                await self._stdio_context.__aexit__(None, None, None)
            except Exception:
                pass
            self._stdio_context = None

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        max_retries: int | None = None,
        base_delay: float | None = None,
    ) -> dict[str, Any]:
        """Call an MCP tool with retry logic.

        Parses the first TextContent item as JSON. Retries on transient
        errors with exponential backoff.

        Args:
            name: MCP tool name to call.
            arguments: Tool arguments dict.
            max_retries: Optional per-call override for retry count.
            base_delay: Optional per-call override for retry delay base.

        Returns:
            Parsed JSON dict from the tool response.

        Raises:
            MCPToolError: Tool returned isError=True after all retries.
            MCPConnectionError: Session not initialized.
            ValueError: Response contains no parseable text content.
        """
        if self._session is None:
            raise MCPConnectionError(
                command=self._server_params.command,
                reason="Session not initialized. Use 'async with MCPClient(...)' context.",
            )

        retries = self._max_retries if max_retries is None else max_retries
        delay_base = self._base_delay if base_delay is None else base_delay

        last_error: str = ""
        call_started = time.perf_counter()
        for attempt in range(retries + 1):
            attempt_started = time.perf_counter()
            DecisionAuditService.log_event_from_context(
                phase="tool_call",
                event_name="mcp.call.started",
                actor="tool",
                tool_name=name,
                payload={
                    "attempt": attempt + 1,
                    "max_attempts": retries + 1,
                    "has_arguments": bool(arguments),
                },
            )
            result = await self._session.call_tool(name, arguments)

            if not result.isError:
                parsed = self._parse_response(name, result)
                DecisionAuditService.log_event_from_context(
                    phase="tool_result",
                    event_name="mcp.call.completed",
                    actor="tool",
                    tool_name=name,
                    payload={
                        "status": "ok",
                        "attempt": attempt + 1,
                        "retry_count": attempt,
                        "total_duration_ms": int((time.perf_counter() - call_started) * 1000),
                    },
                    latency_ms=int((time.perf_counter() - attempt_started) * 1000),
                )
                return parsed

            # Extract error text
            error_text = self._extract_text(result)
            last_error = error_text
            DecisionAuditService.log_event_from_context(
                phase="tool_result",
                event_name="mcp.call.error",
                actor="tool",
                tool_name=name,
                payload={
                    "attempt": attempt + 1,
                    "retry_count": attempt,
                    "error_text": error_text[:500],
                },
                latency_ms=int((time.perf_counter() - attempt_started) * 1000),
            )

            # Check if retryable
            if attempt < retries and self._is_retryable(error_text):
                delay = delay_base * (2 ** attempt)
                logger.warning(
                    "MCP tool '%s' returned retryable error (attempt %d/%d), "
                    "retrying in %.1fs: %s",
                    name, attempt + 1, retries + 1, delay, error_text[:200],
                )
                self._retry_attempts_total += 1
                DecisionAuditService.log_event_from_context(
                    phase="tool_result",
                    event_name="mcp.call.retrying",
                    actor="tool",
                    tool_name=name,
                    payload={
                        "attempt": attempt + 1,
                        "next_delay_seconds": delay,
                    },
                )
                await asyncio.sleep(delay)
                continue

            # Non-retryable or retries exhausted
            break

        DecisionAuditService.log_event_from_context(
            phase="tool_result",
            event_name="mcp.call.failed",
            actor="tool",
            tool_name=name,
            payload={
                "retry_count": retries,
                "error_text": last_error[:500],
                "total_duration_ms": int((time.perf_counter() - call_started) * 1000),
            },
        )
        raise MCPToolError(tool_name=name, error_text=last_error)

    def _parse_response(self, tool_name: str, result: Any) -> dict[str, Any]:
        """Parse tool result into a dict.

        Args:
            tool_name: Name of the tool (for error messages).
            result: CallToolResult from the MCP session.

        Returns:
            Parsed JSON dict.

        Raises:
            ValueError: If no TextContent or invalid JSON.
        """
        text = self._extract_text(result)
        if not text:
            raise ValueError(f"MCP tool '{tool_name}' returned no text content")

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"MCP tool '{tool_name}' returned invalid JSON: {e}"
            ) from e

        if not isinstance(parsed, dict):
            raise ValueError(
                f"MCP tool '{tool_name}' returned {type(parsed).__name__}, expected dict"
            )

        return parsed

    def _extract_text(self, result: Any) -> str:
        """Extract text from the first TextContent in a result.

        Args:
            result: CallToolResult from MCP session.

        Returns:
            Text string, or empty string if no TextContent found.
        """
        for item in result.content:
            if isinstance(item, TextContent):
                return item.text
        return ""
