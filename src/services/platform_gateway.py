# src/services/platform_gateway.py
"""PlatformGateway: runtime client manager for federated platform MCP servers.

Manages per-platform MCP connections with:
- Lazy spawn on first use
- Contract version validation
- Circuit breaker (configurable threshold, per-connection)
- Concurrency limiting via asyncio.Semaphore
- Per-call timeout
- Graceful disconnect and shutdown

The gateway does NOT manage stdio process lifecycle directly —
it delegates to a session_factory callable, making it testable with FakeSession.

Usage:
    gateway = PlatformGateway(registry)
    result = await gateway.call_tool("shopify", "primary", "orders.list", {})
    await gateway.disconnect("shopify", "primary")
    await gateway.shutdown()
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from src.services.platform_models import (
    PlatformConfig,
    PlatformError,
    PlatformErrorCode,
)

logger = logging.getLogger(__name__)

# Default circuit breaker settings
DEFAULT_CIRCUIT_THRESHOLD = 5
DEFAULT_CALL_TIMEOUT = 30.0  # seconds


class CircuitOpenError(PlatformError):
    """Raised when the circuit breaker is open for a connection."""

    def __init__(self, platform_id: str, credential_ref: str, failures: int):
        super().__init__(
            error_code=PlatformErrorCode.TRANSIENT,
            message=(
                f"Circuit breaker open for {platform_id}/{credential_ref} "
                f"after {failures} consecutive failures"
            ),
        )


class SessionProtocol(Protocol):
    """Protocol for MCP session objects (real or fake)."""

    async def call_tool(self, tool_name: str, args: dict) -> dict: ...
    async def close(self) -> None: ...


@dataclass
class PlatformConnection:
    """Runtime state for a single platform connection."""

    platform_id: str
    credential_ref: str
    session: SessionProtocol
    config: PlatformConfig
    created_at: float = field(default_factory=time.monotonic)
    last_used_at: float = field(default_factory=time.monotonic)

    # Circuit breaker state
    consecutive_failures: int = 0
    circuit_open: bool = False

    # Concurrency
    semaphore: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(3))
    active_calls: int = 0

    # Lifecycle
    lifecycle_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class PlatformGateway:
    """Runtime manager for federated platform MCP connections.

    Manages connection lifecycle, circuit breaking, and tool dispatch.
    """

    def __init__(
        self,
        registry: Any,
        session_factory: Callable[[PlatformConfig, str], SessionProtocol] | None = None,
        circuit_threshold: int = DEFAULT_CIRCUIT_THRESHOLD,
        call_timeout_seconds: float = DEFAULT_CALL_TIMEOUT,
    ):
        self._registry = registry
        self._session_factory = session_factory
        self._circuit_threshold = circuit_threshold
        self._call_timeout = call_timeout_seconds
        self._connections: dict[tuple[str, str], PlatformConnection] = {}
        self._connection_locks: dict[tuple[str, str], asyncio.Lock] = {}

    def _get_connection_lock(self, key: tuple[str, str]) -> asyncio.Lock:
        """Get or create a lock for a connection key."""
        if key not in self._connection_locks:
            self._connection_locks[key] = asyncio.Lock()
        return self._connection_locks[key]

    async def _ensure_connection(
        self, platform_id: str, credential_ref: str
    ) -> PlatformConnection:
        """Lazily create a connection, validating the contract on first use."""
        key = (platform_id, credential_ref)
        lock = self._get_connection_lock(key)

        async with lock:
            if key in self._connections:
                return self._connections[key]

            config = self._registry.get_config(platform_id)
            if config is None:
                raise PlatformError(
                    error_code=PlatformErrorCode.INVALID_ARGUMENT,
                    message=f"Unknown platform: {platform_id}",
                )

            # Create session via factory
            if self._session_factory is None:
                raise PlatformError(
                    error_code=PlatformErrorCode.PERMANENT,
                    message="No session factory configured",
                )

            session = self._session_factory(config, credential_ref)

            # Validate contract version via health check
            try:
                health = await session.call_tool("platform.health", {})
            except Exception as e:
                await session.close()
                raise PlatformError(
                    error_code=PlatformErrorCode.TRANSIENT,
                    message=f"Health check failed during connection: {e}",
                ) from e

            server_version = health.get("contract_version")
            if server_version != config.contract_version:
                await session.close()
                raise PlatformError(
                    error_code=PlatformErrorCode.PERMANENT,
                    message=(
                        f"Contract version mismatch for {platform_id}: "
                        f"expected {config.contract_version}, got {server_version}"
                    ),
                )

            # Fetch capabilities
            try:
                caps = await session.call_tool("platform.capabilities", {})
            except Exception as e:
                await session.close()
                raise PlatformError(
                    error_code=PlatformErrorCode.TRANSIENT,
                    message=f"Capabilities fetch failed: {e}",
                ) from e

            # Build connection
            max_concurrency = caps.get("limits", {}).get("max_concurrency", 3)
            conn = PlatformConnection(
                platform_id=platform_id,
                credential_ref=credential_ref,
                session=session,
                config=config,
                semaphore=asyncio.Semaphore(max_concurrency),
            )

            self._connections[key] = conn

            # Update registry state
            try:
                self._registry.update_state(
                    platform_id, credential_ref,
                    connection_status="connected",
                )
            except Exception:
                pass  # Non-critical — don't fail the connection

            return conn

    async def call_tool(
        self,
        platform_id: str,
        credential_ref: str,
        tool_name: str,
        args: dict,
    ) -> dict:
        """Call a tool on a platform MCP server.

        Handles lazy connection, circuit breaking, concurrency, and timeout.
        """
        conn = await self._ensure_connection(platform_id, credential_ref)

        # Circuit breaker check
        if conn.circuit_open:
            raise CircuitOpenError(
                platform_id, credential_ref, conn.consecutive_failures
            )

        # Execute with concurrency control
        async with conn.semaphore:
            conn.active_calls += 1
            try:
                try:
                    result = await asyncio.wait_for(
                        conn.session.call_tool(tool_name, args),
                        timeout=self._call_timeout,
                    )
                except asyncio.TimeoutError:
                    self._record_failure(conn)
                    raise PlatformError(
                        error_code=PlatformErrorCode.TRANSIENT,
                        message=f"Call to {tool_name} timed out after {self._call_timeout}s",
                    )
                except PlatformError as e:
                    # Only trip circuit breaker for circuit-breaker-eligible codes
                    if e.error_code in PlatformErrorCode.circuit_breaker_codes():
                        self._record_failure(conn)
                    raise
                except Exception as e:
                    self._record_failure(conn)
                    raise PlatformError(
                        error_code=PlatformErrorCode.TRANSIENT,
                        message=f"Unexpected error calling {tool_name}: {e}",
                    ) from e

                # Success — reset circuit breaker
                self._record_success(conn)
                conn.last_used_at = time.monotonic()
                return result

            finally:
                conn.active_calls -= 1

    def _record_failure(self, conn: PlatformConnection) -> None:
        """Record a failure for circuit breaker tracking."""
        conn.consecutive_failures += 1
        if conn.consecutive_failures >= self._circuit_threshold:
            conn.circuit_open = True
            logger.warning(
                "Circuit breaker OPEN for %s/%s after %d failures",
                conn.platform_id, conn.credential_ref, conn.consecutive_failures,
            )

    def _record_success(self, conn: PlatformConnection) -> None:
        """Record a success — resets circuit breaker counter."""
        if conn.consecutive_failures > 0:
            logger.info(
                "Circuit breaker reset for %s/%s (was at %d failures)",
                conn.platform_id, conn.credential_ref, conn.consecutive_failures,
            )
        conn.consecutive_failures = 0
        conn.circuit_open = False

    async def disconnect(self, platform_id: str, credential_ref: str) -> None:
        """Disconnect a specific platform connection."""
        key = (platform_id, credential_ref)
        conn = self._connections.pop(key, None)
        if conn is None:
            return

        try:
            await conn.session.close()
        except Exception as e:
            logger.warning("Error closing session for %s/%s: %s", platform_id, credential_ref, e)

        try:
            self._registry.update_state(
                platform_id, credential_ref,
                connection_status="disconnected",
            )
        except Exception:
            pass

    async def shutdown(self) -> None:
        """Gracefully shut down all connections."""
        keys = list(self._connections.keys())
        for platform_id, credential_ref in keys:
            await self.disconnect(platform_id, credential_ref)

    def get_connection(self, platform_id: str, credential_ref: str) -> PlatformConnection | None:
        """Get an existing connection (if any). Does not create one."""
        return self._connections.get((platform_id, credential_ref))

    def list_connections(self) -> list[PlatformConnection]:
        """List all active connections."""
        return list(self._connections.values())
