# Federated Platform MCP with Meta-Orchestrator Tools

**Date:** 2026-02-28
**Status:** Approved
**Scope:** Replace monolithic `external_sources` MCP with per-platform MCP servers + meta-platform agent tools + unified DuckDB import

---

## Problem Statement

ShipAgent currently has a monolithic `ExternalSources` MCP server that houses all platform clients (Shopify, WooCommerce, SAP, Oracle) in one process. Only Shopify is fully wired end-to-end. This model has three fundamental limitations:

1. **Scalability** — adding a new platform (Amazon, eBay) requires modifying the monolithic server, risking regressions in existing integrations.
2. **Isolation** — one platform crashing (e.g., SAP timeout) takes down all platforms. No failure domain separation.
3. **Cross-platform operations** — users cannot query or ship across multiple platforms ("ship all unfulfilled orders from Shopify and Amazon going to Texas").

## Desired State

Any external partner (Shopify, Amazon, WooCommerce, etc.) is supported as an independent MCP server with its own process, lifecycle, and failure domain. A meta-platform tool layer gives the agent a uniform interface to activate, query, and manage platforms without knowing provider specifics. Orders from all platforms land in a single DuckDB table, enabling cross-platform NL filtering and batch shipping.

## Architecture: Federated Platform MCP with Meta-Orchestrator Tools

### Top-Level Structure

```
OrchestrationAgent (Claude Agent SDK)
       |
       +-- Meta-Platform Tools (src/orchestrator/agent/tools/platforms.py)
       |     |  activate_platform, list_platforms, refresh_platform,
       |     |  refresh_all_platforms, disconnect_platform, get_platform_capabilities
       |     |
       |     +-- PlatformRegistry (src/services/platform_registry.py)
       |     |     Static config + persisted dynamic state per (platform_id, credential_ref)
       |     |
       |     +-- PlatformActivationService (src/services/platform_activation_service.py)
       |     |     Connect -> page -> normalize -> upsert -> checkpoint
       |     |
       |     +-- PlatformGateway (src/services/platform_gateway.py)
       |           Lazy MCP client lifecycle, concurrency, circuit breaking
       |           |
       |           +-- ShopifyMCPClient  (stdio -> src/mcp/platforms/shopify/)
       |           +-- AmazonMCPClient   (stdio -> src/mcp/platforms/amazon/)
       |           +-- WooCommerceMCPClient (stdio -> src/mcp/platforms/woocommerce/)
       |           +-- SAPMCPClient      (stdio -> src/mcp/platforms/sap/)
       |           +-- OracleMCPClient   (stdio -> src/mcp/platforms/oracle/)
       |
       +-- Existing tools (data, pipeline, etc.) -- UNCHANGED
       +-- Data Source MCP (DuckDB) -- receives unified flat imports
```

### Key Principles

- **Agent talks only to meta-tools** — never directly to platform MCPs.
- **Meta-tools delegate to services** (Registry, Gateway, ActivationService) — tools are thin dispatchers.
- **Platform MCPs are isolated stdio subprocesses** — per-platform failure domains.
- **DuckDB is the unification plane** — flat columns for NL filtering, `platform` column for discrimination.
- **Existing tools remain untouched** — pipeline, batch, data, interactive tools work as-is.

### What Gets Deleted

| Current | Replacement |
|---------|-------------|
| `src/mcp/external_sources/` (monolithic server) | `src/mcp/platforms/{name}/` (per-platform servers) |
| `src/services/external_sources_mcp_client.py` | `PlatformGateway` + per-platform `call_tool` |
| `src/services/shopify_activation_service.py` | `PlatformActivationService` (generic) |
| `connect_shopify` agent tool | `activate_platform` meta-tool |
| `get_platform_status` agent tool | `list_platforms` meta-tool |
| External sources entry in `gateway_provider.py` | `PlatformGateway` managed via FastAPI lifespan |
| External sources MCP config in `agent/config.py` | Removed — platforms are gateway-managed, not agent-managed |

---

## Section 1: Platform MCP Tool Contract (Leaf Layer)

Every platform MCP server under `src/mcp/platforms/{name}/` implements a rigid, standardized contract so the PlatformGateway stays generic.

### Required Tool Surface

| Tool | Signature | Returns |
|------|-----------|---------|
| `platform.health` | `() -> HealthReport` | `{ ok, platform_id, server_version, contract_version, capabilities_hash, time_utc, api_reachable, auth_valid, last_error? }` |
| `platform.capabilities` | `() -> CapabilityManifest` | `{ platform_id, contract_version, supports[], limits{}, paging{}, writeback{}, filters{} }` |
| `auth.connect` | `(credential_ref) -> AuthResult` | `{ connected, auth_valid, account_id, account_label, scopes?, expires_at? }` |
| `auth.disconnect` | `() -> { disconnected }` | Tears down auth state |
| `orders.list` | `(cursor?, since?, filters?, page_size?) -> OrderPage` | `{ items[], next_cursor?, watermark?, total_estimate? }` |
| `orders.get` | `(order_id) -> ProviderOrder?` | Single order or null |
| `tracking.write_back` | `(order_id, payload: TrackingWriteBackPayload) -> WriteBackResult` | `{ success, error? }` |

Optional tools (declared in capabilities): `orders.delta`, `orders.count`.

### Credential Handling

Platform MCPs **never receive secrets as tool arguments**. `auth.connect` takes a `credential_ref` (logical key like `"shopify_primary"`). The MCP resolves credentials by reading from `KeyringStore` (system keychain) scoped to that ref, falling back to environment variables.

The keyring entry must already exist (configured via Settings UI). No "staging at spawn time" in production paths.

### Paging Invariants

1. **Deterministic ordering** — `(created_at ASC, external_id ASC)`. Same cursor = same page.
2. **Cursor opacity** — opaque string. Gateway never parses or constructs cursors.
3. **Idempotent retries** — `orders.list(cursor=X)` twice returns the same page.
4. **Watermark = last_modified semantics** — captures edits, not just new orders. Initial sync pages by created_at; refresh queries by updated_at/modified_at.
5. **Emulated stability** — if provider doesn't support stable cursor paging, the MCP emulates it internally.
6. **Overlap window** — `paging.overlap_seconds` (default 300). De-duplication handled by PK upsert.
7. **`page_size` parameter** — optional, MCP clamps to `max_page_size`.

### Error Taxonomy

All provider errors normalized to 7 codes:

| Code | Gateway Behavior |
|------|-----------------|
| `AUTH_REQUIRED` | Mark degraded, surface to agent, don't retry |
| `AUTH_EXPIRED` | Mark auth_expired, surface to agent, don't retry |
| `RATE_LIMITED` | Backoff using `retry_after_seconds`, retry up to 3x. Does NOT trip circuit breaker. |
| `NOT_FOUND` | Return null/empty, no retry |
| `INVALID_ARGUMENT` | Return error to agent, no retry |
| `UPSTREAM_ERROR` | Retry once, then mark degraded |
| `TRANSIENT` | Exponential backoff, retry up to 3x |
| `PERMANENT` | Return error to agent, no retry, log |

### Error Response Pattern

Operational failures return a **successful tool response** with `success: false`:

```json
{
  "success": false,
  "error": {
    "error_code": "RATE_LIMITED",
    "message": "...",
    "retry_after_seconds": 2,
    "provider_status": 429,
    "provider_message": "...",
    "request_id": "...",
    "trace_id": "..."
  }
}
```

JSON-RPC hard errors reserved for: malformed request, server bug, contract violation.

### Trace ID Propagation

Standardized `_meta` envelope key in all tool args:

```json
{ "cursor": "abc", "_meta": { "trace_id": "pg-a1b2c3d4e5f6" } }
```

`_meta` is explicitly allowed in all tool JSON schemas. Platform MCPs log `_meta.trace_id` and strip before processing.

### Capabilities Manifest Schema

```json
{
  "platform_id": "shopify",
  "contract_version": "1.0",
  "supports": ["orders.list", "orders.get", "orders.delta", "tracking.write_back"],
  "limits": {
    "max_orders_per_request": 250,
    "rate_limit_per_second": 2,
    "max_concurrency": 3
  },
  "paging": {
    "strategy": "cursor",
    "default_page_size": 50,
    "max_page_size": 250,
    "overlap_seconds": 300
  },
  "writeback": {
    "tracking": true,
    "fulfillment_status": true,
    "returns": false
  },
  "filters": {
    "supported": ["status", "date_range", "fulfillment_status"],
    "unsupported": ["customer_tag", "sku"]
  }
}
```

### Platform MCP Directory Structure

```
src/mcp/platforms/shopify/
    server.py           # FastMCP server (stdio), tool registration (thin)
    client.py           # Shopify API client (httpx)
    models.py           # ProviderOrder, ShopifyCredentials, etc.
    mapper.py           # Shopify order -> flat DuckDB row (pure module, no FastMCP imports)
    constants.py        # API version, endpoints, field limits
    __init__.py
```

Mapper modules must be **pure** — no FastMCP imports, no server-side globals. They know platform-specific field paths but target the system schema. Called by `PlatformActivationService`, not by the MCP server.

---

## Section 2: PlatformRegistry — Static Config + Persisted Dynamic State

### Static Config (code-defined)

```python
@dataclass(frozen=True)
class PlatformConfig:
    platform_id: str                    # "shopify", "amazon", etc.
    display_name: str                   # "Shopify", "Amazon Seller Central"
    default_profile: str                # "primary"
    required_secret_keys: list[str]     # ["ACCESS_TOKEN", "STORE_DOMAIN"] (namespaced per platform in KeyringStore)
    mcp_module: str                     # "src.mcp.platforms.shopify.server"
    mcp_bundle_subcommand: str          # "mcp-shopify"
    contract_version: str               # "1.0" -- must match server's reported version
    default_sync_overlap_seconds: int   # 300
    enabled: bool                       # Feature flag
```

Extension model: add a directory + a `PlatformConfig` entry + credential keys in KeyringStore.

### Dynamic State (persisted in SQLite)

Keyed by `(platform_id, credential_ref)` for multi-account support.

```python
class PlatformSyncState(Base):
    __tablename__ = "platform_sync_state"

    platform_id = Column(String, primary_key=True)
    credential_ref = Column(String, primary_key=True)
    connection_status = Column(String, default="disconnected")  # connected | disconnected | degraded | auth_expired
    account_id = Column(String, nullable=True)
    account_label = Column(String, nullable=True)

    # Sync checkpoints (resumable)
    resume_cursor = Column(String, nullable=True)              # Set during sync, cleared on completion
    last_completed_watermark = Column(String, nullable=True)   # Only advanced on full sync success
    last_sync_completed_at = Column(DateTime(timezone=True), nullable=True)
    last_sync_row_count = Column(Integer, nullable=True)

    # Health tracking
    last_health_check_at = Column(DateTime(timezone=True), nullable=True)
    last_health_ok = Column(Boolean, nullable=True)
    consecutive_failure_count = Column(Integer, default=0)
    last_success_at = Column(DateTime(timezone=True), nullable=True)
    last_error_code = Column(String, nullable=True)
    last_error_message = Column(String, nullable=True)
    last_error_at = Column(DateTime(timezone=True), nullable=True)

    # Capabilities cache
    capabilities_hash = Column(String, nullable=True)
    capabilities_contract_version = Column(String, nullable=True)
    capabilities_json = Column(Text, nullable=True)
    capabilities_fetched_at = Column(DateTime(timezone=True), nullable=True)

    # Metadata
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
```

### State Machine

```
disconnected -> connected      : auth.connect returns auth_valid: true
connected -> degraded          : consecutive_failure_count >= threshold
degraded -> connected          : next successful operation or health check pass
connected/degraded -> auth_expired : AUTH_EXPIRED error from any tool call
                                    OR auth.connect returns auth_valid: false
auth_expired -> connected      : auth.connect with valid credentials succeeds
any -> disconnected            : explicit auth.disconnect call
```

### Checkpoint Semantics (invariant)

- `resume_cursor`: Only set during an in-progress sync. Cleared when sync completes. Used to resume after crash.
- `last_completed_watermark`: Only advanced when a full refresh pass completes successfully. Never advanced mid-sync.

### Contract Version Enforcement

If server's reported `contract_version` mismatches `PlatformConfig.contract_version`, the gateway marks the connection as degraded with `last_error_code="CONTRACT_MISMATCH"` and refuses to proceed.

### PlatformSummary (agent-facing view)

```python
@dataclass
class PlatformSummary:
    platform_id: str
    display_name: str
    credential_ref: str
    enabled: bool
    connection_status: str
    account_label: str | None
    last_sync_completed_at: datetime | None
    last_sync_row_count: int | None
    capabilities: list[str] | None
    has_credentials: bool
    health_ok: bool | None
    last_error: str | None
    contract_version_ok: bool
    capabilities_stale: bool
```

---

## Section 3: PlatformGateway — Lifecycle, Concurrency, and Resilience

### Core Abstraction: PlatformConnection

Each `(platform_id, credential_ref)` gets its own subprocess, semaphore, circuit breaker, and lifecycle lock.

```python
@dataclass
class PlatformConnection:
    platform_id: str
    credential_ref: str
    process: asyncio.subprocess.Process | None = None
    mcp_session: ClientSession | None = None

    # Lifecycle
    spawned_at: datetime | None = None
    last_used_at: datetime | None = None
    active_calls: int = 0              # In-flight call count (reaper safety)

    # Concurrency
    inflight_semaphore: asyncio.Semaphore      # Max concurrent requests (from limits.max_concurrency)
    qps_limiter: TokenBucketLimiter            # QPS enforcement (from limits.rate_limit_per_second)

    # Circuit breaker
    circuit_state: str = "closed"              # closed | open | half_open
    consecutive_failures: int = 0
    circuit_opened_at: datetime | None = None
    probe_in_flight: bool = False              # Half-open exclusivity

    # Lock for lifecycle operations
    lifecycle_lock: asyncio.Lock
```

### Lifecycle: Lazy Spawn + Idle Reap

**Spawn on first use:**
1. Acquire lifecycle_lock
2. Spawn subprocess (stdio_client)
3. MCP initialize handshake
4. Verify contract_version matches PlatformConfig
5. Call auth.connect(credential_ref)
6. Fetch capabilities, configure semaphore + QPS limiter from manifest
7. Update PlatformRegistry dynamic state
8. Release lifecycle_lock

**Idle TTL reaper (background task):**
- Checks every 60 seconds
- Tears down connections where `active_calls == 0` AND idle > TTL (default 300s)
- Acquires lifecycle_lock and re-checks before teardown (race safety)

**Teardown:**
1. Acquire lifecycle_lock
2. Verify active_calls == 0 (re-check)
3. Call auth.disconnect (best-effort)
4. SIGTERM subprocess, SIGKILL after 5s
5. Clear from connections dict
6. Update Registry state
7. Release lifecycle_lock

### Concurrency Control (3 layers)

1. **Per-connection inflight semaphore** — limits concurrent in-flight calls. Set from `limits.max_concurrency` (default 3).
2. **Per-connection QPS limiter** — token bucket enforcing `limits.rate_limit_per_second`. Separate from the semaphore.
3. **Global gateway semaphore** — caps total concurrent platform calls across all connections (default 10).

### Circuit Breaker

```
CLOSED -> OPEN:      consecutive_failures >= 5
OPEN -> HALF_OPEN:   30 seconds elapsed since circuit_opened_at
HALF_OPEN -> CLOSED: probe call succeeds
HALF_OPEN -> OPEN:   probe call fails (reset timer)
```

- `RATE_LIMITED` does NOT increment breaker failures (healthy but throttled).
- Half-open allows exactly one probe call (`probe_in_flight` flag). All other callers fail-fast.

### Per-Call Timeouts

`TOOL_CALL_TIMEOUT_SECONDS` (per-platform override). On timeout:
- Treat as `TRANSIENT`
- Increment failure counters
- Optionally teardown + respawn subprocess

### State Update Queue

Registry updates are queued (not fire-and-forget `create_task`):
- Gateway maintains a single background worker consuming a state update queue
- `call_tool` enqueues state deltas (fast, non-blocking)
- Worker flushes to registry serially
- Deterministic shutdown: drain queue before exit

### Active Call Tracking (reaper safety)

```python
async def call_tool(self, platform_id, credential_ref, tool_name, args, trace_id=None):
    conn = await self._ensure_connection(platform_id, credential_ref)
    conn.active_calls += 1
    try:
        async with self._global_semaphore:
            async with conn.inflight_semaphore:
                await conn.qps_limiter.acquire()
                conn.last_used_at = datetime.now(UTC)
                return await self._dispatch(conn, tool_name, args, trace_id)
    finally:
        conn.active_calls -= 1
```

### Public Interface

```python
class PlatformGateway:
    def __init__(self, registry: PlatformRegistry): ...

    # Lifecycle
    async def startup(self) -> None       # Start reaper. Called from FastAPI lifespan.
    async def shutdown(self) -> None      # Drain queue, teardown all. Called from FastAPI lifespan.

    # Core dispatch
    async def call_tool(self, platform_id, credential_ref, tool_name, args, trace_id=None) -> dict

    # Convenience methods
    async def health_check(self, platform_id, credential_ref) -> HealthReport
    async def get_capabilities(self, platform_id, credential_ref) -> CapabilityManifest
    async def connect(self, platform_id, credential_ref) -> AuthResult
    async def disconnect(self, platform_id, credential_ref) -> None
    async def fetch_orders_page(self, platform_id, credential_ref, cursor?, since?, filters?, page_size?) -> OrderPage
    async def write_back_tracking(self, platform_id, credential_ref, order_id, payload) -> WriteBackResult

    # Observability
    async def get_connection_status(self, platform_id, credential_ref) -> dict
    async def get_all_connections(self) -> list[dict]
```

---

## Section 4: DuckDB Import Schema + Upsert Strategy

### Unified Table Schema

```sql
CREATE TABLE external_orders (
    -- Identity (composite PK)
    platform            VARCHAR NOT NULL,
    external_id         VARCHAR NOT NULL,
    credential_ref      VARCHAR NOT NULL,

    -- Order metadata
    order_number        VARCHAR,
    order_status        VARCHAR,
    payment_status      VARCHAR,
    fulfillment_status  VARCHAR,
    created_at          TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ,

    -- Ship-to address (flat -- NL filter targets)
    ship_to_name        VARCHAR,
    ship_to_company     VARCHAR,
    ship_to_address1    VARCHAR,
    ship_to_address2    VARCHAR,
    ship_to_city        VARCHAR,
    ship_to_state       VARCHAR,
    ship_to_postal      VARCHAR,
    ship_to_country     VARCHAR,
    ship_to_phone       VARCHAR,
    is_residential      BOOLEAN,

    -- Shipment intent
    total_weight_grams  BIGINT,            -- Integer grams (not DOUBLE) for hash stability
    package_count       INTEGER DEFAULT 1,
    shipping_method     VARCHAR,
    service_code        VARCHAR,

    -- Financial
    total_price_cents   BIGINT,
    currency            VARCHAR DEFAULT 'USD',

    -- Enrichment
    customer_name       VARCHAR,
    customer_email      VARCHAR,
    item_count          INTEGER,
    tags                VARCHAR,

    -- Provenance
    canonical_hash      VARCHAR NOT NULL,
    mapping_version     VARCHAR DEFAULT '1.0',
    ingested_at         TIMESTAMPTZ NOT NULL,
    sync_run_id         VARCHAR,

    -- Sidecars (not NL-queryable)
    attrs_json          VARCHAR,
    raw_json            VARCHAR,

    PRIMARY KEY (platform, external_id, credential_ref)
);
```

### Column Promotion Rule

A field becomes a flat column only when it is:
- Used for NL filtering/sorting/routing frequently, OR
- Required for deterministic business logic (payload building), OR
- Needed for joins/analytics

Everything else stays in `attrs_json`.

### Upsert Strategy

Uses `ON CONFLICT DO UPDATE ... WHERE` for atomic, hash-guarded upserts:

```sql
INSERT INTO external_orders ( ... )
VALUES ...
ON CONFLICT (platform, external_id, credential_ref)
DO UPDATE SET
  order_status   = excluded.order_status,
  ...
  canonical_hash = excluded.canonical_hash,
  raw_json       = excluded.raw_json,
  attrs_json     = excluded.attrs_json,
  sync_run_id    = excluded.sync_run_id
WHERE external_orders.canonical_hash <> excluded.canonical_hash;
```

No pre-read of existing hashes in Python. SQL decides whether to update.

### Canonical Hash

Computed over all queryable columns (excluding `canonical_hash`, `ingested_at`, `sync_run_id`, `raw_json`, `attrs_json`). Includes `mapping_version` so a mapper bump forces rewrite.

`total_weight_grams` is BIGINT (not DOUBLE) for hash stability.

### Batch Dedupe

Before upsert, deduplicate within each batch by `(platform, external_id, credential_ref)` keeping latest. Prevents DuckDB errors from duplicate PKs in the same statement (overlap windows and provider quirks).

### Checkpoint Ordering (invariant)

Commit upsert batch THEN persist checkpoint. Never advance `resume_cursor` or watermark if the batch didn't commit.

### Line Items (future, not v1)

```sql
CREATE TABLE external_order_lines (
    platform, external_id, credential_ref, line_id,
    sku, description, quantity, unit_price_cents, weight_grams, hs_code, country_of_origin, raw_json,
    PRIMARY KEY (platform, external_id, credential_ref, line_id)
);
```

---

## Section 5: PlatformActivationService

Plain service module. No MCP, no agent awareness. Fully testable in isolation.

```python
class PlatformActivationService:
    def __init__(self, registry, gateway, data_gateway): ...

    async def activate_platform(self, platform_id, credential_ref, mode="initial") -> ActivationReport
    async def activate_multiple(self, platforms: list[tuple], mode="refresh") -> list[ActivationReport]
```

### Activation Flow

```
1. VALIDATE
   - registry.get_config() -- exists? enabled?
   - registry.get_state() -- current state
   - KeyringStore check -- credentials present for all required_secret_keys

2. CONNECT
   - gateway.connect(platform_id, credential_ref)
   - gateway.get_capabilities() -- cache in registry
   - Verify "orders.list" in capabilities

3. DETERMINE SYNC WINDOW
   - initial: cursor = state.resume_cursor or None, since = None
   - refresh: cursor = state.resume_cursor or None,
              since = last_completed_watermark - overlap_seconds

4. PAGE LOOP
   sync_run_id = generate_run_id()
   while True:
     page = gateway.fetch_orders_page(...)
     normalized = [mapper.to_flat_row(order) for order in page.items]
     dedupe by PK within batch
     data_gateway.upsert_records(normalized, "external_orders")
     CHECKPOINT: registry.record_sync_checkpoint(resume_cursor=page.next_cursor)
     if page.next_cursor is None: break

5. FINALIZE
   registry.record_sync_checkpoint(
       resume_cursor=None,                    # Clear
       watermark=page.watermark,              # Advance NOW
       row_count=total_imported)

6. RETURN ActivationReport
```

### Sync Modes

| Aspect | Initial | Refresh |
|--------|---------|---------|
| `since` | None (full pull) | last_completed_watermark - overlap |
| Dedup | Upsert by PK | Upsert by PK + hash skip |
| Watermark | Set from final page | Advance from final page |
| Volume | All orders | Changed/new only |

---

## Section 6: Agent-Side Meta-Tools

### Tool Surface

| Tool | Purpose |
|------|---------|
| `list_platforms` | Show available platforms + status + capabilities |
| `activate_platform` | Connect and import orders |
| `refresh_platform` | Incremental re-sync (thin wrapper: activate with mode="refresh") |
| `refresh_all_platforms` | Re-sync all connected platforms in parallel |
| `disconnect_platform` | Tear down connection, optionally purge DuckDB data |
| `get_platform_capabilities` | Return platform's capability manifest |

### Design Rules

- All tools are **batch-mode only** (hidden in interactive mode). Enforced in tool dispatcher, not just UI.
- `platform_id` validated against `PlatformRegistry.list_configs(enabled_only=True)` at runtime. NOT hardcoded as a static enum in JSON schema.
- Tools are thin: validate args, call service, return report. No retries, paging, or business logic.

### Cross-Platform Query Flow (end to end)

```
User: "Ship all unfulfilled orders from Shopify and Amazon going to Texas, UPS Ground"

Agent calls: ship_command_pipeline({
    filter: "platform IN ('shopify', 'amazon') AND ship_to_state = 'TX'
             AND fulfillment_status = 'unfulfilled'",
    service: "ground"
})

ship_command_pipeline (UNCHANGED):
  -> Data Source MCP: SELECT * FROM external_orders WHERE ...
  -> Creates job, runs batch_preview
  -> Returns PreviewCard

User confirms -> batch_execute (UNCHANGED except write-back routing):
  -> UPS MCP: create_shipment per row
  -> On success per row:
     Read platform + credential_ref from ROW COLUMNS (not order_data blob)
     Check capability cache (fetched once per platform per run)
     If tracking.write_back supported:
       gateway.write_back_tracking(platform, credential_ref, external_id, payload)
       -> Routes to correct platform MCP automatically
```

### System Prompt Addition

```
## External Platforms

You can connect to external e-commerce platforms to import orders for shipping.
Use `list_platforms` to see available integrations and their status.
Use `activate_platform` to connect and import orders.
Once imported, orders appear in the data source with a `platform` column.

Cross-platform queries work naturally:
- "Ship all unfulfilled orders from Shopify and Amazon going to Texas"
  -> filter: WHERE platform IN ('shopify', 'amazon') AND ship_to_state = 'TX'
             AND fulfillment_status = 'unfulfilled'

The `platform` column is always available for filtering when external orders are loaded.
```

### Write-Back Routing

```python
# In BatchEngine, after successful create_shipment:
platform = row.platform            # Column, not blob
credential_ref = row.credential_ref
order_id = row.external_id

if platform and credential_ref:
    caps = capabilities_cache[(platform, credential_ref)]  # Fetched once per run
    if "tracking.write_back" in caps.get("supports", []):
        await gateway.write_back_tracking(platform, credential_ref, order_id, payload)
```

### Data Source MCP Changes

Two additions to `src/mcp/data_source/`:
1. `upsert_records` tool — `INSERT ... ON CONFLICT DO UPDATE ... WHERE hash differs`
2. `platform` awareness in schema introspection

Everything else (query, filter, writeback) unchanged.

---

## Migration Path (3 phases, no flag day)

### Phase A: Build New Alongside Old

1. Create `src/mcp/platforms/shopify/` (extract from `external_sources`)
2. Build `PlatformRegistry`, `PlatformGateway`, `PlatformActivationService`
3. Add `external_orders` DuckDB table + upsert support to Data Source MCP
4. Register new meta-tools alongside old `connect_shopify`

### Phase B: Switch Over

5. Point `connect_shopify` at `activate_platform("shopify")` internally (thin shim)
6. Update `BatchEngine` write-back to use `PlatformGateway`
7. Update Settings UI to use new `/api/v1/platforms/*` endpoints

### Phase C: Clean Up + Expand

8. Remove `connect_shopify` shim + old tool registrations
9. Delete `src/mcp/external_sources/`, `ExternalSourcesMCPClient`, `ShopifyActivationService`
10. Extract WooCommerce/SAP/Oracle into `src/mcp/platforms/{name}/`
11. Add Amazon platform

Each phase is independently deployable and testable.

---

## Locked Invariants

1. Platform MCPs never receive secrets as tool args. `credential_ref` pattern only.
2. `resume_cursor` clears on sync completion. `last_completed_watermark` only advances on full sync success.
3. Commit upsert batch THEN persist checkpoint. Never the reverse.
4. `RATE_LIMITED` does not trip the circuit breaker.
5. `platform_id` enum validated at runtime from registry, not hardcoded in tool schema.
6. Write-back reads `platform`/`credential_ref` from row columns, not serialized blobs.
7. Mapper modules are pure (no FastMCP imports, no server globals).
8. Contract version mismatch = immediate degraded state, connection refused.
9. Half-open circuit allows exactly one probe call (exclusive flag).
10. Capabilities cached per (platform, credential_ref) per batch run for write-back (not per-row).
