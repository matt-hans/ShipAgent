# Phase 2: Data Source MCP — Context

Decisions that guide research and planning for Phase 2 implementation.

---

## Schema Discovery Behavior

### Mixed Type Handling
**Decision:** Default to string when column contains mixed data types.

**Rationale:** Safest approach — no data loss. If a column has "123", "ABC", "456", treat entire column as text. User can override if needed.

### Date Parsing
**Decision:** Auto-detect common formats with ambiguity warnings.

**Supported formats:**
- ISO 8601 (`2026-01-24`, `2026-01-24T10:30:00Z`)
- US format (`MM/DD/YYYY`, `M/D/YY`)
- EU format (`DD/MM/YYYY`, `D/M/YY`)
- Excel serial dates

**Ambiguity handling:** When a date like `01/02/03` could be interpreted multiple ways, flag with warning and ask user to clarify or default to US format.

### Type Override
**Decision:** Allow per-column type override after import.

User can say "treat order_id as string not number" after seeing inferred schema. Avoids re-import for minor inference mistakes.

### Numeric Precision
**Decision:** Preserve as-is.

Store "1.50" as "1.50" — don't strip trailing zeros, don't normalize. The mapping templates handle any necessary conversion.

---

## Data Source Boundaries

### Multi-Source Model
**Decision:** One source at a time.

Importing a new source replaces the previous one. Keeps the mental model simple: there's always exactly one "active" data source.

### Source-Job Relationship
**Decision:** Job references source snapshot.

When a job is created:
1. System records which source was active
2. Captures row checksums at that moment
3. Job always works with that immutable snapshot

If source changes after job creation, job still sees original data.

### Session Lifecycle
**Decision:** Ephemeral — reload each session.

Data lives in memory/temp storage during session. When session ends, data is gone. Next session, user re-imports. This ensures:
- No stale data
- No storage bloat
- Simple cleanup

### Write-Back Timing
**Decision:** On job completion only.

Tracking numbers are written back to the source file/database after ALL shipments in a job succeed. Atomic: all or nothing. Partial success doesn't modify source.

---

## Error Handling on Import

### Missing Required Fields
**Decision:** Import all rows, flag invalid ones.

Import always succeeds. Rows missing required fields (recipient address, etc.) are flagged with validation warnings. User sees which rows need fixing before creating a job.

### Empty Rows
**Decision:** Silently skip.

Blank rows in CSV/Excel are ignored. Don't count them, don't warn about them. They're noise.

### Malformed Data
**Decision:** Best-effort parsing.

Try to parse intelligently:
- Strip commas from numbers (`1,234.56` → `1234.56`)
- Handle currency symbols (`$50.00` → `50.00`)
- Normalize whitespace

If parsing fails, keep as string. Let mapping templates handle conversion.

### Error Threshold
**Decision:** No threshold — report all errors.

Import proceeds regardless of error count. User sees full error report. If 90% of rows are invalid, that's useful information — don't hide it by failing early.

---

## Database Connection Semantics

### Connection Model
**Decision:** Snapshot on import.

Query runs once at import time, results cached locally (same as loading a file). Consistent with ephemeral session model. No persistent connections.

### Credentials Handling
**Decision:** Connection string only, never stored.

User provides full connection string each session:
```
postgresql://user:pass@host:5432/dbname
mysql://user:pass@host:3306/dbname
```

Nothing persisted. Security-first: no credential storage.

### Supported Databases
**Decision:** PostgreSQL and MySQL.

Covers 90%+ of shipping/order systems. SQLite and SQL Server deferred — can add later if needed.

### Large Table Protection
**Decision:** Require WHERE clause for tables > 10,000 rows.

If user selects a large table with no filter, prompt:
> "This table has 50,000 rows. Add a filter (e.g., WHERE order_date > '2026-01-01') or confirm you want all rows."

Prevents accidental massive imports.

---

## Deferred Ideas

None captured during discussion.

---

## Summary for Downstream Agents

| Area | Key Decision |
|------|--------------|
| Type inference | Default to string on ambiguity; allow override |
| Dates | Auto-detect common formats; warn on ambiguous |
| Multi-source | One at a time; import replaces previous |
| Job snapshot | Immutable reference to source at creation time |
| Session | Ephemeral; reload each session |
| Write-back | On job completion only; atomic |
| Bad rows | Import all, flag invalid; no threshold |
| Empty rows | Silent skip |
| Parsing | Best-effort; fall back to string |
| DB model | Snapshot, not live connection |
| Credentials | Never stored; connection string per session |
| DB support | PostgreSQL + MySQL |
| Large tables | Require filter if > 10k rows |

---

*Created: 2026-01-24*
