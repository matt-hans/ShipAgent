# Integration Expansion Design

**Date:** 2026-01-26
**Status:** Draft
**Goal:** Expand ShipAgent to support ~90% of UPS customers through EDI, ERP, and ecommerce integrations

---

## Problem Statement

ShipAgent currently supports file-based data sources (CSV, Excel, Database). This limits reach to customers who can export their data manually. To capture the broader UPS customer base:

- **50-60%** use EDI (X12/EDIFACT) for B2B transactions
- **40-50%** use ERP systems (SAP, Oracle, Microsoft Dynamics)
- **25-35%** use ecommerce platforms (Shopify, WooCommerce)

## Solution Overview

Two new components extend ShipAgent's data ingestion:

1. **EDI Adapter** — Parse EDI files as a data source (extends existing adapter pattern)
2. **External Sources Gateway MCP** — Unified client to platform MCP servers (Shopify, WooCommerce, SAP, Oracle)

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        ShipAgent Orchestrator                        │
│                      (Claude Agent SDK + FastAPI)                    │
└───────────────┬─────────────────┬─────────────────┬─────────────────┘
                │                 │                 │
         ┌──────▼──────┐   ┌──────▼──────┐   ┌──────▼──────┐
         │ Data Source │   │ External    │   │   UPS       │
         │ MCP         │   │ Sources MCP │   │   MCP       │
         │ (existing)  │   │ (new)       │   │ (existing)  │
         └──────┬──────┘   └──────┬──────┘   └─────────────┘
                │                 │
    ┌───────────┼───────────┐     │
    │           │           │     │
┌───▼───┐ ┌─────▼─────┐ ┌───▼───┐ │
│ CSV   │ │  Excel    │ │ EDI   │ │ (MCP Client connections)
│Adapter│ │ Adapter   │ │Adapter│ │         │
└───────┘ └───────────┘ └───────┘ │    ┌────┴────┬─────────┬──────────┐
                (new)             │    ▼         ▼         ▼          ▼
                                  │ Shopify  WooCommerce  SAP      Oracle
                                  │ MCP       MCP         MCP       MCP
                                  │(external)(external) (external)(external)
```

## Component 1: EDI Adapter

Extends `BaseSourceAdapter` to parse EDI files into DuckDB.

### Supported Formats

| Standard | Transaction | Purpose | Key Fields |
|----------|-------------|---------|------------|
| X12 | 850 | Purchase Order | ship-to address, items, quantities, PO number |
| X12 | 856 | ASN | shipment details, tracking, carrier info |
| X12 | 810 | Invoice | billing address, amounts, references |
| EDIFACT | ORDERS | Purchase Order | equivalent to 850 |
| EDIFACT | DESADV | Dispatch Advice | equivalent to 856 |
| EDIFACT | INVOIC | Invoice | equivalent to 810 |

### Implementation

```python
class EDIAdapter(BaseSourceAdapter):
    @property
    def source_type(self) -> str:
        return "edi"

    def import_data(self, conn, file_path: str, **kwargs) -> ImportResult:
        # 1. Detect format (X12 vs EDIFACT) from file content
        # 2. Detect transaction type (850/856/810 or equivalent)
        # 3. Parse using appropriate parser
        # 4. Normalize to common schema
        # 5. Load into DuckDB 'imported_data' table
```

### Parser Libraries

- **X12:** [pyx12](https://github.com/azoner/pyx12)
- **EDIFACT:** [pydifact](https://github.com/nerdocs/pydifact)

### Schema Normalization

All transaction types normalize to common shipping-relevant columns:
- `recipient_name`, `recipient_company`
- `address_line1`, `address_line2`, `city`, `state`, `postal_code`, `country`
- `items` (JSON array), `quantities`, `weights`
- `po_number`, `reference_number`

## Component 2: External Sources Gateway MCP

New MCP server acting as unified client to external platform MCPs.

### Tools Exposed to Orchestrator

| Tool | Purpose |
|------|---------|
| `list_connections` | Show configured platform connections and status |
| `connect_platform` | Establish/refresh OAuth connection |
| `list_orders` | Fetch orders with optional filters |
| `import_orders` | Pull orders into DuckDB |
| `get_order_details` | Fetch full details for specific order |
| `write_back_tracking` | Push tracking numbers to source platform |

### Platform Abstraction

```python
class PlatformClient(ABC):
    @abstractmethod
    async def authenticate(self, credentials: dict) -> bool: ...

    @abstractmethod
    async def fetch_orders(self, filters: OrderFilters) -> list[Order]: ...

    @abstractmethod
    async def update_order_tracking(self, order_id: str, tracking: str) -> bool: ...
```

### Platform Implementations

#### WooCommerce
- **Source:** [techspawn/woocommerce-mcp-server](https://github.com/techspawn/woocommerce-mcp-server)
- **Status:** Ready to use
- **Auth:** Consumer key + secret
- **Capabilities:** Full order CRUD, tracking write-back

#### Shopify
- **Source:** Fork of [GeLi2001/shopify-mcp](https://github.com/GeLi2001/shopify-mcp)
- **Status:** Requires extension (missing fulfillment tools)
- **Auth:** Admin API access token
- **New tools needed:**
  - `get-fulfillment-orders`
  - `create-fulfillment`
  - `add-tracking-info`

#### SAP
- **Source:** [GutjahrAI/sap-odata-mcp-server](https://glama.ai/mcp/servers/@GutjahrAI/sap-odata-mcp-server)
- **Status:** Ready to use
- **Auth:** Username/password + client number
- **Tools:** 11 OData tools including `sap_query_entity_set`, `sap_update_entity`

#### Oracle
- **Source:** [oracle/mcp](https://github.com/oracle/mcp) (oracle-db-mcp-java-toolkit)
- **Status:** SQL-level access (requires customer schema config)
- **Auth:** OCI CLI profile
- **Approach:** Direct SQL queries against order tables

## Data Flow

```
User Command → Orchestrator ─┬→ Data Source MCP ──────→ DuckDB → Batch Executor → UPS MCP
                             │   (CSV/Excel/DB/EDI)              ↓
                             │                              Write-back
                             └→ External Sources MCP ─────→     ↓
                                 (Shopify/WooCommerce/     ┌────┴────┐
                                  SAP/Oracle)              ▼         ▼
                                      ↑                  Data     External
                                      └──────────────── Source    Sources
                                         write-back      MCP       MCP
```

**Key points:**
1. Both MCPs load to same DuckDB `imported_data` table format
2. Schema normalization handles platform-specific differences
3. Dual write-back path based on source type
4. Job metadata tracks source for correct write-back routing

## Error Handling

### Connection Failures
| Scenario | Behavior |
|----------|----------|
| Platform unreachable | Retry 3x with exponential backoff, then surface error |
| OAuth expired | Auto-refresh or prompt re-authentication |
| Rate limit | Queue requests, respect `Retry-After`, warn user |

### Data Inconsistencies
| Scenario | Behavior |
|----------|----------|
| Order modified during batch | Checksum mismatch → halt, show changed orders |
| Missing required fields | Flag row invalid, continue with valid rows |
| Schema changed | Best-effort mapping, surface unmapped fields |

### Write-back Failures
| Scenario | Behavior |
|----------|----------|
| Partial failure | Track per-order success/failure, allow retry |
| Platform rejects | Log reason, mark "shipped but write-back failed" |
| Connection lost | Resume via crash recovery, per-row state persisted |

### EDI-Specific
| Scenario | Behavior |
|----------|----------|
| Invalid syntax | Parse error with line number, reject file |
| Unknown transaction | Reject with supported types list |
| Mixed standards | Reject files mixing X12/EDIFACT |

## Implementation Phases

### Phase 1: EDI Adapter
- Implement `EDIAdapter` extending `BaseSourceAdapter`
- X12 parser (850, 856, 810) using pyx12
- EDIFACT parser (ORDERS, DESADV, INVOIC) using pydifact
- Schema normalization
- Integration tests

### Phase 2: External Sources Gateway MCP
- MCP server scaffolding with FastMCP
- `PlatformClient` interface
- Connection management
- Unified tool interface

### Phase 3: WooCommerce Connector
- Integrate techspawn MCP server
- `WooCommerceClient` wrapper
- Test order import + tracking write-back

### Phase 4: Shopify Connector
- Fork GeLi2001/shopify-mcp
- Add fulfillment tools
- `ShopifyClient` wrapper
- Test full flow

### Phase 5: SAP Connector
- Integrate SAP OData MCP
- `SAPClient` with sales order mapping
- SAP-specific auth handling
- Test with S/4HANA or ECC

### Phase 6: Oracle Connector
- Integrate Oracle DB MCP
- `OracleClient` with configurable schema
- Customer provides table mapping
- Test with Oracle order tables

## Coverage Impact

| Component | Effort | New Coverage |
|-----------|--------|--------------|
| EDI Adapter | Medium | +50-60% (enterprise B2B) |
| WooCommerce | Low | +5-10% (SMB ecommerce) |
| Shopify | Medium | +10-15% (SMB ecommerce) |
| SAP | Low | +20-25% (enterprise ERP) |
| Oracle | Medium | +10-15% (enterprise ERP) |

**Total: ~75-90% of UPS customers**

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| EDI as adapter | Fits existing `BaseSourceAdapter` pattern |
| Unified gateway MCP | Single integration point for orchestrator |
| Fork Shopify MCP | Add missing fulfillment tools |
| Leverage existing MCPs | WooCommerce, SAP, Oracle servers already exist |
| Inbound-only EDI | Read files only, no AS2/SFTP transport (YAGNI) |
| X12 + EDIFACT | International B2B support from day one |

## Out of Scope

- EDI transport protocols (AS2, SFTP) — users upload files manually
- Outbound EDI generation (856 ASN creation)
- BigCommerce, Magento, other ecommerce platforms
- Microsoft Dynamics connector (can add later)
- Multi-account per platform

## References

- [WooCommerce MCP Docs](https://developer.woocommerce.com/docs/features/mcp/)
- [Shopify Dev MCP](https://shopify.dev/docs/apps/build/devmcp)
- [SAP OData MCP Server](https://glama.ai/mcp/servers/@GutjahrAI/sap-odata-mcp-server)
- [Oracle MCP Repository](https://github.com/oracle/mcp)
- [pyx12 (X12 parser)](https://github.com/azoner/pyx12)
- [pydifact (EDIFACT parser)](https://github.com/nerdocs/pydifact)
