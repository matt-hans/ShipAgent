# Stack Research: ShipAgent

**Project:** Natural Language Batch Shipment Processing System
**Researched:** 2026-01-23
**Research Mode:** Ecosystem (Stack Dimension)

---

## Executive Summary

This research identifies the optimal technology stack for building ShipAgent - a natural language interface for batch shipment processing. The recommended stack aligns with the project's architecture requirements (MCP, Claude Agent SDK, deterministic batch execution) while prioritizing production readiness, developer experience, and maintainability.

**Core Finding:** The stack outlined in CLAUDE.md is well-aligned with 2025/2026 best practices. This research validates those choices and provides specific version recommendations with rationale.

---

## Recommended Stack

### Backend / Orchestration

| Technology | Version | Purpose | Confidence | Rationale |
|------------|---------|---------|------------|-----------|
| **Python** | 3.11+ | Core runtime | HIGH | Required by Claude Agent SDK. 3.11 offers significant performance improvements and better typing. 3.12+ acceptable but 3.11 is most stable for SDK compatibility. |
| **Claude Agent SDK** | Latest (pip: `claude-agent-sdk`) | LLM orchestration | HIGH | Official Anthropic SDK for agentic workflows. Provides MCP integration, tool management, and the agent loop that powers Claude Code. Bundled CLI included. |
| **Anthropic Python SDK** | 0.75.0+ | API client | HIGH | Core dependency of Agent SDK. Provides async/sync clients, type definitions, and httpx-based networking. |
| **FastAPI** | 0.115+ | Web framework | HIGH | Async-native, automatic OpenAPI docs, Pydantic v2 integration. Standard for Python AI/ML APIs in 2025. |
| **Pydantic** | 2.12+ | Data validation | HIGH | Core rewritten in Rust for 5-50x performance. Required by FastAPI. Provides runtime validation and serialization. |
| **Jinja2** | 3.1.6 | Template engine | HIGH | Stable, well-documented. Required for mapping templates (data -> UPS payload). Supports custom filters essential for logistics transformations. |
| **httpx** | 0.27+ | HTTP client | HIGH | Async support, HTTP/2, connection pooling. Used internally by Anthropic SDK. Better than requests for async FastAPI apps. |

**Sources:**
- [Anthropic Python SDK - PyPI](https://pypi.org/project/anthropic/)
- [Claude Agent SDK - GitHub](https://github.com/anthropics/claude-agent-sdk-python)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Pydantic Documentation](https://docs.pydantic.dev/latest/)
- [Jinja2 - PyPI](https://pypi.org/project/Jinja2/)

### Data Processing

| Technology | Version | Purpose | Confidence | Rationale |
|------------|---------|---------|------------|-----------|
| **DuckDB** | 1.1+ | SQL analytics engine | HIGH | In-process OLAP database. 10-1000x faster than SQLite for analytics. Zero dependencies, pip installable. Queries CSV/Excel/Parquet directly without loading into memory. Perfect for batch data processing. |
| **Pandas** | 2.2+ | DataFrame operations | MEDIUM | Still needed for ML pipeline integration and wide ecosystem support. DuckDB can query Pandas DataFrames directly. Use for small transforms, DuckDB for heavy lifting. |
| **openpyxl** | 3.1+ | Excel reading/writing | HIGH | Only library that both reads AND writes .xlsx files. Required for write-back of tracking numbers to Excel sources. |
| **gspread** | 6.1+ | Google Sheets API | MEDIUM | Mature wrapper for Google Sheets. Note: maintainers seeking new owners as of 2025 - monitor for alternatives. Requires google-auth. |

**Note on Polars:** While Polars is 10-30x faster than Pandas, DuckDB provides similar performance benefits with SQL interface that's better suited for LLM-generated queries. Polars adds complexity without clear benefit for this use case.

**Sources:**
- [DuckDB Python Guide](https://betterstack.com/community/guides/scaling-python/duckdb-python/)
- [DuckDB vs Pandas - DigitalOcean](https://www.digitalocean.com/community/tutorials/duckdb-complements-pandas-for-large-scale-analytics)
- [openpyxl vs XlsxWriter](https://stringfestanalytics.com/how-to-understand-the-difference-between-the-openpyxl-and-xlsxwriter-python-packages-for-excel/)
- [gspread - PyPI](https://pypi.org/project/gspread/)

### MCP (Model Context Protocol)

| Technology | Version | Purpose | Confidence | Rationale |
|------------|---------|---------|------------|-----------|
| **MCP Python SDK** | 1.x (pip: `mcp`) | Data Source MCP | HIGH | Official SDK for building MCP servers. v1.x recommended for production (v2 in alpha, stable Q1 2026). |
| **MCP TypeScript SDK** | Latest (`@modelcontextprotocol/sdk`) | UPS Shipping MCP | HIGH | Official SDK. Peer dependency on Zod. TypeScript provides better type safety for complex API schemas. |
| **Zod** | 4.3+ | Schema validation (TS) | HIGH | v4 released July 2025 with 14x faster parsing, 57% smaller core. Required peer dep for MCP TS SDK. |

**Sources:**
- [MCP Python SDK - GitHub](https://github.com/modelcontextprotocol/python-sdk)
- [MCP TypeScript SDK - GitHub](https://github.com/modelcontextprotocol/typescript-sdk)
- [Zod v4 Release - InfoQ](https://www.infoq.com/news/2025/08/zod-v4-available/)

### UPS Integration

| Technology | Version | Purpose | Confidence | Rationale |
|------------|---------|---------|------------|-----------|
| **Direct UPS REST API** | OAuth 2.0 | Shipping, Rating, Tracking | HIGH | Use REST API directly (not SOAP). Modern, well-documented. No mature Python SDK - custom client recommended. |
| **Zod** | 4.3+ | Request/response validation | HIGH | Generate Zod schemas from UPS OpenAPI spec. Provides compile-time type safety AND runtime validation. |
| **axios/fetch** | Latest | HTTP requests (TS) | MEDIUM | Standard for TypeScript HTTP. Consider ky or ofetch for modern features. |

**Anti-pattern:** Don't use ClassicUPS or PyUPS - these are outdated wrappers for legacy SOAP APIs.

**Sources:**
- [UPS Developer Portal](https://developer.ups.com/)
- [UPS API Integration Guide - Apidog](https://apidog.com/blog/ups-apis-developer-guide/)

### Frontend

| Technology | Version | Purpose | Confidence | Rationale |
|------------|---------|---------|------------|-----------|
| **React** | 19.x | UI framework | HIGH | React 19 is stable with Server Components, improved TypeScript inference, React Compiler (auto-memoization). Industry standard. |
| **TypeScript** | 5.8+ | Type safety | HIGH | Non-negotiable for React in 2025. Strict mode required. |
| **Vite** | 6.x | Build tool | HIGH | Replaced CRA as standard. Near-instant HMR, native ESM, Rollup for production builds. Use `react-ts` template. |
| **TanStack Query** | 5.x | Server state | HIGH | Replaces Redux for API data. Automatic caching, background refetching, optimistic updates. Perfect for shipment status polling. |
| **Tailwind CSS** | 4.x | Styling | MEDIUM | Utility-first CSS. Fast iteration. Consider shadcn/ui for component library. |

**Sources:**
- [React 19 + TypeScript Best Practices](https://medium.com/@CodersWorld99/react-19-typescript-best-practices-the-new-rules-every-developer-must-follow-in-2025-3a74f63a0baf)
- [Vite Getting Started](https://vite.dev/guide/)
- [TanStack Query Overview](https://tanstack.com/query/latest/docs/framework/react/overview)

### Database / State

| Technology | Version | Purpose | Confidence | Rationale |
|------------|---------|---------|------------|-----------|
| **SQLite** | 3.45+ | Dev/local state | HIGH | Zero config, file-based. Perfect for development and single-user deployments. |
| **aiosqlite** | 0.21+ | Async SQLite | HIGH | AsyncIO bridge to SQLite. Required for non-blocking state writes in FastAPI. |
| **PostgreSQL** | 16+ | Production state | HIGH | ACID compliance, JSONB for flexible schemas, excellent async driver support. |
| **SQLModel** | 0.0.22+ | ORM | MEDIUM | SQLAlchemy + Pydantic combined. Same author as FastAPI. Simplifies model definitions. For complex queries, drop to SQLAlchemy. |

**Alternative:** SQLAlchemy 2.0+ with async support if you need more control or have existing SQLAlchemy experience.

**Sources:**
- [aiosqlite - PyPI](https://pypi.org/project/aiosqlite/)
- [SQLModel Documentation](https://sqlmodel.tiangolo.com/)
- [SQLModel vs SQLAlchemy 2025](https://python.plainenglish.io/sqlmodel-in-2025-the-hidden-gem-of-fastapi-backends-20ee8c9bf8a6)

### Development Tools

| Technology | Version | Purpose | Confidence | Rationale |
|------------|---------|---------|------------|-----------|
| **ruff** | 0.8+ | Linting + Formatting | HIGH | Replaces flake8, black, isort, pyupgrade. 10-100x faster. Adopted by FastAPI, Pandas, Pydantic. Single tool, single config. |
| **pytest** | 9.0+ | Python testing | HIGH | De facto standard. Rich plugin ecosystem. Async support via pytest-asyncio. |
| **pytest-asyncio** | 1.3+ | Async test support | HIGH | Required for testing async FastAPI endpoints and aiosqlite operations. |
| **pytest-cov** | 7.0+ | Coverage reporting | HIGH | Coverage measurement for pytest. |
| **Vitest** | 3.x | TypeScript testing | HIGH | 10-20x faster than Jest. Native ESM/TypeScript. Jest-compatible API for easy migration. |
| **ESLint** | 9.x | TS linting | HIGH | Standard for TypeScript. Use flat config format. |
| **Prettier** | 3.x | TS formatting | HIGH | Opinionated formatting. Integrate with ESLint. |
| **pre-commit** | Latest | Git hooks | HIGH | Enforce linting/formatting before commits. |
| **uv** | 0.5+ | Python package manager | HIGH | 10-100x faster than pip. Drop-in replacement. From Astral (ruff creators). |
| **pnpm** | 9.x | Node package manager | HIGH | Faster and more disk-efficient than npm. Strict by default. |

**Sources:**
- [Ruff Documentation](https://docs.astral.sh/ruff/)
- [Ruff vs Black/Flake8](https://medium.com/@zigtecx/why-you-should-replace-flake8-black-and-isort-with-ruff-the-ultimate-python-code-quality-tool-a9372d1ddc1e)
- [pytest - PyPI](https://pypi.org/project/pytest/)
- [Vitest vs Jest 2025](https://medium.com/@ruverd/jest-vs-vitest-which-test-runner-should-you-use-in-2025-5c85e4f2bda9)

---

## What NOT to Use

### Python

| Technology | Why Not | Use Instead |
|------------|---------|-------------|
| **requests** | No async support, blocks event loop in FastAPI | httpx |
| **black + flake8 + isort** | Three tools, slow, conflicting configs | ruff (all-in-one) |
| **pip** | Slow dependency resolution | uv |
| **Pandas alone for large data** | Single-threaded, memory-hungry | DuckDB for queries, Pandas for small transforms |
| **SQLAlchemy 1.x** | Legacy sync-only API | SQLAlchemy 2.0+ or SQLModel |
| **Flask** | Sync-only, no built-in validation | FastAPI |
| **Django** | Overkill for API-focused project, heavy | FastAPI |

### TypeScript

| Technology | Why Not | Use Instead |
|------------|---------|-------------|
| **Jest** | Slow, complex ESM/TS config | Vitest |
| **Create React App (CRA)** | Deprecated, unmaintained | Vite |
| **npm** | Slower, less disk-efficient | pnpm |
| **Redux (for server state)** | Boilerplate-heavy for API data | TanStack Query |
| **Zod v3** | v4 is 14x faster, smaller | Zod v4 |
| **React.FC type** | Implicit children prop, discouraged | Explicit prop interfaces |

### UPS Integration

| Technology | Why Not | Use Instead |
|------------|---------|-------------|
| **ClassicUPS** | Outdated, limited coverage | Direct REST API |
| **PyUPS** | Legacy SOAP wrapper | Direct REST API |
| **Shippo/EasyPost** | Third-party abstraction adds cost, latency, dependency | Direct UPS API (for UPS-only MVP) |

---

## Installation Commands

### Python Dependencies

```bash
# Use uv for faster installs
pip install uv

# Core dependencies
uv pip install \
    anthropic \
    claude-agent-sdk \
    fastapi \
    uvicorn \
    pydantic \
    httpx \
    jinja2 \
    duckdb \
    pandas \
    openpyxl \
    gspread \
    google-auth \
    aiosqlite \
    sqlmodel

# Dev dependencies
uv pip install \
    pytest \
    pytest-asyncio \
    pytest-cov \
    ruff \
    pre-commit
```

### TypeScript Dependencies (UPS MCP)

```bash
# Initialize with pnpm
pnpm init

# Core dependencies
pnpm add @modelcontextprotocol/sdk zod typescript

# Dev dependencies
pnpm add -D vitest @types/node eslint prettier typescript
```

### Frontend Dependencies

```bash
# Create Vite React TypeScript project
npm create vite@latest shipagent-ui -- --template react-ts
cd shipagent-ui

# Core dependencies
pnpm add @tanstack/react-query axios

# Dev dependencies
pnpm add -D vitest @testing-library/react @testing-library/jest-dom
```

---

## Confidence Assessment Summary

| Category | Confidence | Notes |
|----------|------------|-------|
| **Backend/Orchestration** | HIGH | Claude Agent SDK and FastAPI are well-documented, officially supported |
| **Data Processing** | HIGH | DuckDB and openpyxl are proven, stable choices |
| **MCP** | HIGH | Official SDKs from Anthropic/MCP consortium |
| **UPS Integration** | MEDIUM | Direct API integration well-documented, but no official SDK means custom implementation |
| **Frontend** | HIGH | React 19, Vite, TanStack Query are mature, widely adopted |
| **Database** | HIGH | SQLite/PostgreSQL are battle-tested; SQLModel is newer but backed by FastAPI author |
| **Dev Tools** | HIGH | ruff, pytest, Vitest are industry standards with strong adoption |

---

## Version Pinning Strategy

For production stability, pin major.minor versions:

```toml
# pyproject.toml example
[project]
dependencies = [
    "anthropic>=0.75,<1.0",
    "fastapi>=0.115,<0.120",
    "pydantic>=2.12,<3.0",
    "duckdb>=1.1,<2.0",
    "jinja2>=3.1,<4.0",
    "httpx>=0.27,<1.0",
]
```

---

## Open Questions for Phase-Specific Research

1. **UPS OAuth Flow:** Exact implementation of OAuth 2.0 token refresh for long-running batch jobs
2. **Google Sheets Auth:** Service account vs OAuth for multi-user scenarios
3. **WebSocket vs SSE:** For real-time batch progress updates to frontend
4. **Error Recovery:** Retry strategies for partial batch failures

---

**Research Status:** COMPLETE
**Files Created:** `.planning/research/STACK.md`
