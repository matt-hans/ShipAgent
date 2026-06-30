# OpenAI Widget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the OpenAI Apps widget surface for rates, immutable preview, explicit execute-button confirmation, job progress, and label download actions.

**Architecture:** Keep shipment execution, approval grants, job references, and label streaming in the Plan 7 control-plane/workflow services. Plan 8 registers MCP Apps HTML resources from canonical `ui_resource` tool fields, serves the Angular `provider-widget` bundle as first-party static assets, and lets the widget consume Plan 6 `OPENAI_WIDGET_META` through the OpenAI/MCP Apps bridge. The OpenAI model never receives `execute_shipments`; only the widget calls the app-only tool after a user button gesture.

**Tech Stack:** Python 3.12, FastAPI, FastMCP resources, Pydantic settings, pytest, Angular 21 standalone components, Angular custom elements, Nx 22, Vitest/Angular unit tests, OpenAI Apps SDK/MCP Apps bridge.

---

## Source Of Truth

Authoritative design:

```text
docs/superpowers/specs/2026-06-10-openai-claude-connector-design.md
```

Plan 8 implements only this slice from the spec:

- `provider-widget`: rates, preview/confirm with the execute button gesture, job progress, label download action
- MCP Apps HTML resources served through existing `ToolContract.ui_resource` fields
- OpenAI widget visibility and app-only `execute_shipments` descriptor emitted by Plan 6
- `OPENAI_WIDGET_META` data as widget-only metadata, never model-visible content
- preview/confirm, job progress, and label download behavior coordinated with Plan 7 endpoints

Secondary OpenAI docs checked for Apps HTML resource and bridge mechanics:

```text
https://developers.openai.com/apps-sdk/reference
https://developers.openai.com/apps-sdk/build/mcp-server
https://developers.openai.com/apps-sdk/build/chatgpt-ui
https://developers.openai.com/apps-sdk/deploy/troubleshooting
```

Important current repo state inspected:

```text
AGENTS.md
src/AGENTS.md
shipagent-frontend/AGENTS.md
src/registry/models.py
src/registry/tools/public.py
src/provider_adapters/openai_projection.py
src/provider_adapters/mcp_projection.py
src/hosted_mcp/server.py
src/control_plane/app.py
src/control_plane/config.py
tests/provider_adapters/test_projections.py
tests/registry/test_artifact_drift.py
tests/hosted/test_hosted_mcp_registry.py
tests/e2e/test_portability_smoke.py
shipagent-frontend/apps/provider-widget/project.json
shipagent-frontend/apps/provider-widget/src/main.ts
shipagent-frontend/apps/provider-widget/src/app/preview-widget.component.ts
shipagent-frontend/package.json
shipagent-frontend/nx.json
```

Observed starting points:

- `ToolContract.ui_resource` already exists.
- Current OpenAI projection emits `_meta.ui.resourceUri` when `ui_resource` is present.
- Plan 6 owns `_meta.ui.visibility: ["app"]` for OpenAI `execute_shipments`, output profiles, and `OPENAI_WIDGET_META`.
- Current `src/hosted_mcp/server.py` registers tools only. It does not register MCP resources.
- Current `provider-widget` is an indexless Angular custom element scaffold with one sample component and no test/typecheck targets.
- `generated/provider_artifacts/*.json` are generated outputs. Regenerate with `scripts/generate_provider_artifacts.py`; never hand-edit generated artifacts.

## File Structure

Create:

```text
src/hosted_mcp/widget_resources.py
tests/hosted/test_openai_widget_resources.py
tests/registry/test_openai_widget_ui_resources.py
shipagent-frontend/apps/provider-widget/tsconfig.spec.json
shipagent-frontend/apps/provider-widget/src/app/openai-host-bridge.service.ts
shipagent-frontend/apps/provider-widget/src/app/openai-host-bridge.service.spec.ts
shipagent-frontend/apps/provider-widget/src/app/openai-widget.models.ts
shipagent-frontend/apps/provider-widget/src/app/openai-widget.state.ts
shipagent-frontend/apps/provider-widget/src/app/openai-widget.state.spec.ts
shipagent-frontend/apps/provider-widget/src/app/provider-widget.component.ts
shipagent-frontend/apps/provider-widget/src/app/provider-widget.component.spec.ts
```

Modify:

```text
src/control_plane/app.py
src/control_plane/config.py
src/hosted_mcp/server.py
src/registry/tools/public.py
tests/control_plane/test_app_auth.py
tests/provider_adapters/test_projections.py
shipagent-frontend/apps/provider-widget/project.json
shipagent-frontend/apps/provider-widget/src/main.ts
shipagent-frontend/apps/provider-widget/src/styles.css
```

Modify by generator only:

```text
generated/provider_artifacts/openai_apps_public_tools.json
generated/provider_artifacts/registry.json
```

Do not modify in this plan:

```text
src/control_plane/result_projection.py
src/control_plane/relay/
src/control_plane/approval*
src/services/
src/orchestrator/
shipagent-frontend/apps/chat-remote/
shipagent-frontend/apps/settings-remote/
generated/provider_artifacts/*.json by hand
```

The boundary is deliberate:

- Plan 6 supplies schema, visibility, and `OPENAI_WIDGET_META` redaction.
- Plan 7 supplies real `prepare_shipments`, `execute_shipments`, `get_job_status`, and `create_label_download` handlers.
- Plan 8 supplies widget resources, widget rendering, bridge calls, and widget tests.
- Plan 10 supplies adversarial golden prompt coverage after Plans 7 and 8 land.

---

### Task 1: Register OpenAI Widget HTML Resources

**Files:**

- Create: `src/hosted_mcp/widget_resources.py`
- Modify: `src/hosted_mcp/server.py`
- Test: `tests/hosted/test_openai_widget_resources.py`

- [ ] **Step 1: Write failing resource registration tests**

Create `tests/hosted/test_openai_widget_resources.py`.

```python
import pytest

from src.hosted_mcp.server import build_server
from src.hosted_mcp.widget_resources import OPENAI_WIDGET_MIME_TYPE
from src.registry.catalog import public_tools
from src.registry.models import ProviderExport


def _tool(name: str):
    return next(tool for tool in public_tools() if tool.name == name)


def _openai_exportable_tool(name: str):
    return _tool(name).model_copy(
        update={
            "implementation_status": "implemented",
            "hosted_readiness": "ready",
            "provider_export_enabled": True,
            "provider_exports": [ProviderExport.openai_apps_public],
        }
    )


@pytest.mark.asyncio
async def test_build_server_registers_widget_resources_from_ui_resource_fields():
    server = build_server(
        tools=[
            _openai_exportable_tool("get_shipment_rates"),
            _openai_exportable_tool("prepare_shipments"),
            _openai_exportable_tool("execute_shipments"),
            _openai_exportable_tool("get_job_status").model_copy(
                update={"ui_resource": "ui://shipagent/progress.html"}
            ),
            _openai_exportable_tool("create_label_download").model_copy(
                update={"ui_resource": "ui://shipagent/labels.html"}
            ),
        ],
        tool_handlers={},
        widget_asset_base_url="https://dev-mcp.shipagent.app/openai-widget/assets",
    )

    resources = await server.get_resources()

    assert {
        "ui://shipagent/rates.html",
        "ui://shipagent/preview.html",
        "ui://shipagent/confirmation.html",
        "ui://shipagent/progress.html",
        "ui://shipagent/labels.html",
    }.issubset(resources)

    preview = resources["ui://shipagent/preview.html"]
    assert preview.mime_type == OPENAI_WIDGET_MIME_TYPE
    assert preview.meta == {
        "openai/widgetDescription": "Review the immutable ShipAgent shipment preview before purchase.",
        "openai/widgetPrefersBorder": True,
        "openai/widgetCSP": {
            "connect_domains": [],
            "resource_domains": ["https://dev-mcp.shipagent.app"],
        },
        "openai/widgetDomain": "https://dev-mcp.shipagent.app",
    }


@pytest.mark.asyncio
async def test_widget_resource_html_bootstraps_provider_widget_for_each_mode():
    server = build_server(
        tools=[
            _openai_exportable_tool("get_shipment_rates"),
            _openai_exportable_tool("prepare_shipments"),
            _openai_exportable_tool("execute_shipments"),
        ],
        tool_handlers={},
        widget_asset_base_url="https://dev-mcp.shipagent.app/openai-widget/assets",
    )

    resources = await server.get_resources()
    rates_html = await resources["ui://shipagent/rates.html"].read()
    preview_html = await resources["ui://shipagent/preview.html"].read()
    confirmation_html = await resources["ui://shipagent/confirmation.html"].read()

    assert '<shipagent-provider-widget mode="rates">' in rates_html
    assert '<shipagent-provider-widget mode="preview">' in preview_html
    assert '<shipagent-provider-widget mode="confirmation">' in confirmation_html
    assert 'src="https://dev-mcp.shipagent.app/openai-widget/assets/main.js"' in preview_html
    assert "raw_ups" not in preview_html.lower()
    assert "label_base64" not in preview_html.lower()


@pytest.mark.asyncio
async def test_unknown_ui_resource_fails_closed_during_server_build():
    bad_tool = _openai_exportable_tool("prepare_shipments").model_copy(
        update={"ui_resource": "ui://shipagent/unknown.html"}
    )

    with pytest.raises(ValueError) as exc:
        build_server(
            tools=[bad_tool],
            tool_handlers={},
            widget_asset_base_url="https://dev-mcp.shipagent.app/openai-widget/assets",
        )

    assert str(exc.value) == "No OpenAI widget resource registered for ui://shipagent/unknown.html"
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
.venv/bin/python -m pytest tests/hosted/test_openai_widget_resources.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.hosted_mcp.widget_resources'`.

- [ ] **Step 3: Add the widget resource registry**

Create `src/hosted_mcp/widget_resources.py`.

```python
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from urllib.parse import urlparse

from fastmcp import FastMCP
from fastmcp.resources.types import TextResource

from src.registry.models import ProviderExport, ToolContract

OPENAI_WIDGET_MIME_TYPE = "text/html;profile=mcp-app"


@dataclass(frozen=True)
class WidgetResource:
    uri: str
    mode: str
    title: str
    description: str


WIDGET_RESOURCES: dict[str, WidgetResource] = {
    "ui://shipagent/rates.html": WidgetResource(
        uri="ui://shipagent/rates.html",
        mode="rates",
        title="ShipAgent Rates",
        description="Compare ShipAgent rate options returned by the shipment rating tool.",
    ),
    "ui://shipagent/preview.html": WidgetResource(
        uri="ui://shipagent/preview.html",
        mode="preview",
        title="ShipAgent Preview",
        description="Review the immutable ShipAgent shipment preview before purchase.",
    ),
    "ui://shipagent/confirmation.html": WidgetResource(
        uri="ui://shipagent/confirmation.html",
        mode="confirmation",
        title="ShipAgent Confirmation",
        description="Confirm the exact priced ShipAgent shipment preview before execution.",
    ),
    "ui://shipagent/progress.html": WidgetResource(
        uri="ui://shipagent/progress.html",
        mode="progress",
        title="ShipAgent Progress",
        description="Track ShipAgent shipment execution progress.",
    ),
    "ui://shipagent/labels.html": WidgetResource(
        uri="ui://shipagent/labels.html",
        mode="labels",
        title="ShipAgent Labels",
        description="Create an authenticated ShipAgent label download action for a completed job.",
    ),
}


def register_openai_widget_resources(
    server: FastMCP,
    tools: list[ToolContract],
    *,
    widget_asset_base_url: str,
) -> None:
    for uri in _openai_widget_uris(tools):
        resource = WIDGET_RESOURCES.get(uri)
        if resource is None:
            raise ValueError(f"No OpenAI widget resource registered for {uri}")
        server.add_resource(
            TextResource(
                uri=resource.uri,
                name=resource.title,
                title=resource.title,
                description=resource.description,
                mime_type=OPENAI_WIDGET_MIME_TYPE,
                text=_render_widget_html(resource, widget_asset_base_url),
                meta=_resource_meta(resource, widget_asset_base_url),
            )
        )


def _openai_widget_uris(tools: list[ToolContract]) -> list[str]:
    uris = {
        tool.ui_resource
        for tool in tools
        if tool.ui_resource
        and ProviderExport.openai_apps_public in tool.provider_exports
    }
    return sorted(uri for uri in uris if uri is not None)


def _render_widget_html(resource: WidgetResource, widget_asset_base_url: str) -> str:
    mode = escape(resource.mode, quote=True)
    script_src = escape(_asset_url(widget_asset_base_url, "main.js"), quote=True)
    stylesheet_href = escape(_asset_url(widget_asset_base_url, "styles.css"), quote=True)
    title = escape(resource.title)
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
    <link rel="stylesheet" href="{stylesheet_href}">
  </head>
  <body>
    <shipagent-provider-widget mode="{mode}"></shipagent-provider-widget>
    <script type="module" src="{script_src}"></script>
  </body>
</html>
"""


def _resource_meta(
    resource: WidgetResource,
    widget_asset_base_url: str,
) -> dict[str, object]:
    origin = _origin(widget_asset_base_url)
    resource_domains = [origin] if origin else []
    return {
        "openai/widgetDescription": resource.description,
        "openai/widgetPrefersBorder": True,
        "openai/widgetCSP": {
            "connect_domains": [],
            "resource_domains": resource_domains,
        },
        "openai/widgetDomain": origin or "https://chatgpt.com",
    }


def _asset_url(widget_asset_base_url: str, file_name: str) -> str:
    return f"{widget_asset_base_url.rstrip('/')}/{file_name}"


def _origin(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"
```

- [ ] **Step 4: Register resources from the hosted MCP server builder**

In `src/hosted_mcp/server.py`, add this import:

```python
from src.hosted_mcp.widget_resources import register_openai_widget_resources
```

Change the `build_server()` signature to accept the asset URL:

```python
def build_server(
    tool_handlers: Mapping[str, ToolHandler] | None = None,
    tools: Iterable[ToolContract] | None = None,
    request_controls: RequestControls | None = None,
    widget_asset_base_url: str = "/openai-widget/assets",
) -> FastMCP:
```

At the start of `build_server()`, materialize the tool list once and register widget resources:

```python
def build_server(
    tool_handlers: Mapping[str, ToolHandler] | None = None,
    tools: Iterable[ToolContract] | None = None,
    request_controls: RequestControls | None = None,
    widget_asset_base_url: str = "/openai-widget/assets",
) -> FastMCP:
    server = FastMCP("ShipAgentHosted")
    handlers = tool_handlers or {}
    configured_tools = list(tools) if tools is not None else public_tools()
    register_openai_widget_resources(
        server,
        configured_tools,
        widget_asset_base_url=widget_asset_base_url,
    )
    for tool in exportable_tools(ProviderExport.generic_mcp, configured_tools):
        handler = handlers.get(tool.name)
        if handler is None:
            continue
        descriptor = to_mcp_tool_descriptor(tool)
        server.add_tool(
            BoundRegistryTool(
                name=tool.name,
                title=tool.title,
                description=tool.description,
                parameters=descriptor["inputSchema"],
                output_schema=descriptor["outputSchema"],
                annotations=ToolAnnotations(**descriptor["annotations"]),
                contract=tool,
                handler=handler,
                request_controls=request_controls,
            )
        )
    return server
```

Also add `public_tools` to the existing registry import in `src/hosted_mcp/server.py`:

```python
from src.registry.catalog import public_tools
```

- [ ] **Step 5: Run the resource tests**

Run:

```bash
.venv/bin/python -m pytest tests/hosted/test_openai_widget_resources.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit the resource registration**

```bash
git add src/hosted_mcp/server.py src/hosted_mcp/widget_resources.py tests/hosted/test_openai_widget_resources.py
git commit -m "feat: register OpenAI widget resources"
```

---

### Task 2: Wire Widget Resource URIs Into Public Tool Contracts

**Files:**

- Modify: `src/registry/tools/public.py`
- Test: `tests/registry/test_openai_widget_ui_resources.py`
- Test: `tests/provider_adapters/test_projections.py`
- Generated by command: `generated/provider_artifacts/openai_apps_public_tools.json`
- Generated by command: `generated/provider_artifacts/registry.json`

- [ ] **Step 1: Write failing registry tests for Plan 8 resource coverage**

Create `tests/registry/test_openai_widget_ui_resources.py`.

```python
from src.registry.catalog import public_tools


def _tool(name: str):
    return next(tool for tool in public_tools() if tool.name == name)


def test_openai_widget_tools_have_expected_ui_resources():
    assert _tool("get_shipment_rates").ui_resource == "ui://shipagent/rates.html"
    assert _tool("prepare_shipments").ui_resource == "ui://shipagent/preview.html"
    assert _tool("execute_shipments").ui_resource == "ui://shipagent/confirmation.html"
    assert _tool("get_job_status").ui_resource == "ui://shipagent/progress.html"
    assert _tool("create_label_download").ui_resource == "ui://shipagent/labels.html"
```

Append this test to `tests/provider_adapters/test_projections.py`.

```python
def test_openai_job_and_label_tools_include_widget_resource_meta():
    job_descriptor = to_openai_app_tool(tool("get_job_status"))
    label_descriptor = to_openai_app_tool(tool("create_label_download"))

    assert job_descriptor["_meta"]["ui"]["resourceUri"] == "ui://shipagent/progress.html"
    assert label_descriptor["_meta"]["ui"]["resourceUri"] == "ui://shipagent/labels.html"
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
.venv/bin/python -m pytest tests/registry/test_openai_widget_ui_resources.py tests/provider_adapters/test_projections.py -v -k "openai_widget_tools or openai_job_and_label"
```

Expected: FAIL because `get_job_status` and `create_label_download` do not yet declare widget resources.

- [ ] **Step 3: Add progress and label widget resource URIs to public tools**

In `src/registry/tools/public.py`, update the `get_job_status` public tool block by adding `ui_resource`:

```python
    public_tool(
        "get_job_status",
        "Get job status",
        "Get the status and progress summary for a ShipAgent job.",
        SideEffectClass.read,
        ["jobs:read"],
        object_schema(
            {"job_id": {"type": "string", "description": "ShipAgent job identifier."}},
            ["job_id"],
        ),
        object_schema(
            {"job_id": {"type": "string"}, "status": {"type": "string"}},
            ["job_id", "status"],
        ),
        ui_resource="ui://shipagent/progress.html",
    ),
```

In the same file, update the `create_label_download` public tool block by adding `ui_resource`:

```python
    public_tool(
        "create_label_download",
        "Create label download",
        "Create downloadable label artifacts for a completed shipment job.",
        SideEffectClass.read,
        ["labels:read"],
        object_schema(
            {"job_id": {"type": "string"}},
            ["job_id"],
        ),
        object_schema(
            {"download_url": {"type": "string"}, "status": {"type": "string"}},
            ["download_url", "status"],
        ),
        ui_resource="ui://shipagent/labels.html",
    ),
```

If Plan 6 has already replaced legacy scopes with `shipagent.*` scopes and renamed `job_id` to `job_ref`, keep those Plan 6 names and add only the `ui_resource` lines shown here.

- [ ] **Step 4: Run the registry and projection tests**

Run:

```bash
.venv/bin/python -m pytest tests/registry/test_openai_widget_ui_resources.py tests/provider_adapters/test_projections.py -v -k "openai_widget_tools or openai_job_and_label"
```

Expected: PASS.

- [ ] **Step 5: Regenerate provider artifacts**

Run:

```bash
.venv/bin/python scripts/generate_provider_artifacts.py
```

Expected: command exits 0 and updates generated artifacts from the registry.

- [ ] **Step 6: Verify artifact drift**

Run:

```bash
.venv/bin/python -m pytest tests/registry/test_artifact_drift.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit registry resource wiring**

```bash
git add src/registry/tools/public.py tests/registry/test_openai_widget_ui_resources.py tests/provider_adapters/test_projections.py generated/provider_artifacts/openai_apps_public_tools.json generated/provider_artifacts/registry.json
git commit -m "feat: link OpenAI widget resources to public tools"
```

---

### Task 3: Serve Provider Widget Static Assets From The Control Plane

**Files:**

- Modify: `src/control_plane/config.py`
- Modify: `src/control_plane/app.py`
- Test: `tests/control_plane/test_app_auth.py`

- [ ] **Step 1: Write failing tests for first-party widget asset serving**

Append this test to `tests/control_plane/test_app_auth.py`.

```python
def test_widget_assets_are_public_first_party_static_files(monkeypatch, tmp_path):
    asset_dir = tmp_path / "provider-widget"
    asset_dir.mkdir()
    (asset_dir / "main.js").write_text("customElements.define('x-test', class extends HTMLElement {});\n", encoding="utf-8")
    (asset_dir / "styles.css").write_text(":root { color: #111827; }\n", encoding="utf-8")

    app = _build_app_with_routes(
        monkeypatch,
        "sqlite+aiosqlite:///:memory:",
        openai_widget_asset_dir=str(asset_dir),
    )

    with TestClient(app) as client:
        response = client.get("/openai-widget/assets/main.js")

    assert response.status_code == 200
    assert "customElements.define" in response.text
    assert response.headers["content-type"].startswith("text/javascript")
```

Change `_build_app_with_routes()` in `tests/control_plane/test_app_auth.py` to accept the new optional asset directory:

```python
def _build_app_with_routes(monkeypatch, database_url: str, openai_widget_asset_dir: str | None = None):
    monkeypatch.setenv("SHIPAGENT_PUBLIC_BASE_URL", "https://dev-mcp.shipagent.app/")
    monkeypatch.setenv("SHIPAGENT_AUTH0_ISSUER", "https://tenant.us.auth0.com/")
    monkeypatch.setenv("SHIPAGENT_AUTH0_AUDIENCE", "https://dev-mcp.shipagent.app")
    monkeypatch.setenv("SHIPAGENT_DATABASE_URL", database_url)
    monkeypatch.setenv("SHIPAGENT_REDIS_URL", "redis://127.0.0.1:6379/0")
    if openai_widget_asset_dir is not None:
        monkeypatch.setenv("SHIPAGENT_OPENAI_WIDGET_ASSET_DIR", openai_widget_asset_dir)
```

- [ ] **Step 2: Run the failing control-plane test**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_app_auth.py -v -k widget_assets
```

Expected: FAIL with a 401 or 404 response for `/openai-widget/assets/main.js`.

- [ ] **Step 3: Add the widget asset directory setting**

In `src/control_plane/config.py`, add `Path` to the imports:

```python
from pathlib import Path
```

Add this field to `ControlPlaneSettings`:

```python
    openai_widget_asset_dir: Path = Path("shipagent-frontend/dist/apps/provider-widget/browser")
```

- [ ] **Step 4: Mount static widget assets and pass the public asset URL to MCP resources**

In `src/control_plane/app.py`, add imports:

```python
from pathlib import Path

from fastapi.staticfiles import StaticFiles
```

Add these helper functions below `_metadata_url()`:

```python
def _public_base_url(settings: ControlPlaneSettings) -> str:
    if settings.public_base_url is None:
        raise RuntimeError("SHIPAGENT_PUBLIC_BASE_URL must be set")
    return str(settings.public_base_url).rstrip("/")


def _widget_asset_base_url(settings: ControlPlaneSettings) -> str:
    return f"{_public_base_url(settings)}/openai-widget/assets"


def _widget_asset_dir(settings: ControlPlaneSettings) -> Path:
    return Path(settings.openai_widget_asset_dir)
```

Replace:

```python
    mcp = build_server(request_controls=_build_request_controls(settings))
```

with:

```python
    mcp = build_server(
        request_controls=_build_request_controls(settings),
        widget_asset_base_url=_widget_asset_base_url(settings),
    )
```

After `app.include_router(...)`, mount the asset directory only when it exists:

```python
    widget_asset_dir = _widget_asset_dir(settings)
    if widget_asset_dir.exists():
        app.mount(
            "/openai-widget/assets",
            StaticFiles(directory=widget_asset_dir),
            name="openai-widget-assets",
        )
```

In `_require_authorization()`, permit public static widget assets before bearer-token checks:

```python
        if request.url.path.startswith("/openai-widget/assets/"):
            return await call_next(request)
```

- [ ] **Step 5: Run the control-plane asset test**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_app_auth.py -v -k "widget_assets or valid_token or missing_token"
```

Expected: PASS.

- [ ] **Step 6: Commit widget asset serving**

```bash
git add src/control_plane/app.py src/control_plane/config.py tests/control_plane/test_app_auth.py
git commit -m "feat: serve OpenAI widget assets"
```

---

### Task 4: Add Provider Widget Test And Build Targets

**Files:**

- Create: `shipagent-frontend/apps/provider-widget/tsconfig.spec.json`
- Modify: `shipagent-frontend/apps/provider-widget/project.json`

- [ ] **Step 1: Add the provider-widget spec TypeScript config**

Create `shipagent-frontend/apps/provider-widget/tsconfig.spec.json`.

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "../../dist/out-tsc/provider-widget-spec",
    "types": ["vitest/globals"]
  },
  "include": ["src/**/*.spec.ts", "src/**/*.d.ts"]
}
```

- [ ] **Step 2: Update provider-widget Nx targets**

Replace `shipagent-frontend/apps/provider-widget/project.json` with:

```json
{
  "name": "provider-widget",
  "$schema": "../../node_modules/nx/schemas/project-schema.json",
  "projectType": "application",
  "sourceRoot": "apps/provider-widget/src",
  "targets": {
    "build": {
      "executor": "@angular/build:application",
      "outputs": ["{options.outputPath}"],
      "options": {
        "outputPath": "dist/apps/provider-widget",
        "browser": "apps/provider-widget/src/main.ts",
        "index": false,
        "tsConfig": "apps/provider-widget/tsconfig.app.json",
        "styles": ["apps/provider-widget/src/styles.css"]
      },
      "configurations": {
        "production": {
          "optimization": true,
          "extractLicenses": true,
          "sourceMap": false,
          "outputHashing": "none"
        }
      },
      "defaultConfiguration": "production"
    },
    "typecheck": {
      "executor": "nx:run-commands",
      "options": {
        "command": "tsc --noEmit -p apps/provider-widget/tsconfig.app.json"
      },
      "cache": true,
      "inputs": ["default", "^default"]
    },
    "test": {
      "executor": "@angular/build:unit-test",
      "options": {}
    }
  }
}
```

- [ ] **Step 3: Run provider-widget target discovery**

Run:

```bash
cd shipagent-frontend
npx nx show project provider-widget
```

Expected: output lists `build`, `typecheck`, and `test` targets for `provider-widget`.

- [ ] **Step 4: Run provider-widget typecheck**

Run:

```bash
cd shipagent-frontend
npx nx typecheck provider-widget
```

Expected: PASS while the widget still contains the sample component.

- [ ] **Step 5: Commit Nx target setup**

```bash
git add shipagent-frontend/apps/provider-widget/project.json shipagent-frontend/apps/provider-widget/tsconfig.spec.json
git commit -m "test: add provider widget validation targets"
```

---

### Task 5: Implement The OpenAI Host Bridge

**Files:**

- Create: `shipagent-frontend/apps/provider-widget/src/app/openai-widget.models.ts`
- Create: `shipagent-frontend/apps/provider-widget/src/app/openai-host-bridge.service.ts`
- Create: `shipagent-frontend/apps/provider-widget/src/app/openai-host-bridge.service.spec.ts`

- [ ] **Step 1: Add widget model types**

Create `shipagent-frontend/apps/provider-widget/src/app/openai-widget.models.ts`.

```typescript
export type WidgetMode = 'rates' | 'preview' | 'confirmation' | 'progress' | 'labels';

export interface WidgetSummary {
  shipment_count?: number;
  warning_count?: number;
  total_charge?: number;
  currency?: string;
}

export interface RateOption {
  id: string;
  carrier?: string;
  service?: string;
  service_name?: string;
  total_charge?: number;
  currency?: string;
  estimated_delivery?: string;
  selected?: boolean;
}

export interface WidgetStructuredContent {
  status?: string;
  reason?: string;
  terminal?: boolean;
  message?: string;
  preview_ref?: string;
  preview_id?: string;
  job_ref?: string;
  job_id?: string;
  download_url?: string;
  summary?: WidgetSummary;
  rates?: RateOption[];
  selected?: string;
  progress?: {
    completed?: number;
    failed?: number;
    needs_review?: number;
    not_started?: number;
    total?: number;
  };
}

export interface WidgetActionMeta {
  execute_tool?: 'execute_shipments';
  get_job_status_tool?: 'get_job_status';
  create_label_download_tool?: 'create_label_download';
  preview_ref?: string;
  preview_hash?: string;
  execution_grant_ref?: string;
  approval_request_ref?: string;
  job_ref?: string;
  idempotency_key?: string;
  selected_rate_id?: string;
  authorized_amount?: number;
  currency?: string;
  label_download_ref?: string;
}

export interface OpenAiToolResult {
  structuredContent: WidgetStructuredContent;
  content: unknown[];
  meta: WidgetActionMeta;
}

export interface OpenAiToolsBridge {
  call(request: { name: string; arguments?: Record<string, unknown> }): Promise<unknown>;
}

export interface OpenAiBridge {
  toolInput?: unknown;
  toolOutput?: WidgetStructuredContent | null;
  toolResponseMetadata?: {
    status?: string;
    call_tool_result?: unknown;
    mcp_tool_result?: unknown;
    _meta?: WidgetActionMeta;
  } | null;
  widgetState?: unknown;
  tools?: OpenAiToolsBridge;
  setWidgetState?: (state: unknown) => void;
}

export interface OpenAiAppsWindow {
  openai?: OpenAiBridge;
  addEventListener(type: 'message', listener: EventListener): void;
  removeEventListener(type: 'message', listener: EventListener): void;
  open(url?: string, target?: string, features?: string): Window | null;
}
```

- [ ] **Step 2: Write failing host bridge tests**

Create `shipagent-frontend/apps/provider-widget/src/app/openai-host-bridge.service.spec.ts`.

```typescript
import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';
import {
  OPENAI_WINDOW,
  OpenAiHostBridgeService,
} from './openai-host-bridge.service';
import { OpenAiAppsWindow } from './openai-widget.models';

class FakeWindow implements OpenAiAppsWindow {
  readonly listeners = new Set<EventListener>();
  openai = {
    toolOutput: {
      status: 'preview_ready',
      summary: { shipment_count: 2, total_charge: 18.44, currency: 'USD' },
    },
    toolResponseMetadata: {
      mcp_tool_result: {
        structuredContent: {
          status: 'preview_ready',
          summary: { shipment_count: 2, total_charge: 18.44, currency: 'USD' },
        },
        content: [],
        _meta: {
          execute_tool: 'execute_shipments' as const,
          preview_ref: 'prv_123',
          execution_grant_ref: 'gr_openai_123',
        },
      },
    },
    tools: {
      call: vi.fn().mockResolvedValue({
        structuredContent: { status: 'running', job_ref: 'job_123' },
        content: [],
        _meta: { job_ref: 'job_123' },
      }),
    },
    setWidgetState: vi.fn(),
  };

  addEventListener(type: 'message', listener: EventListener): void {
    if (type === 'message') {
      this.listeners.add(listener);
    }
  }

  removeEventListener(type: 'message', listener: EventListener): void {
    if (type === 'message') {
      this.listeners.delete(listener);
    }
  }

  open(): Window | null {
    return null;
  }

  emitMessage(data: unknown): void {
    const event = { data } as MessageEvent;
    for (const listener of this.listeners) {
      listener(event);
    }
  }
}

describe('OpenAiHostBridgeService', () => {
  it('reads structured content and widget-only metadata from toolResponseMetadata', () => {
    const fakeWindow = new FakeWindow();
    TestBed.configureTestingModule({
      providers: [{ provide: OPENAI_WINDOW, useValue: fakeWindow }],
    });

    const service = TestBed.inject(OpenAiHostBridgeService);

    expect(service.readInitialToolResult()).toEqual({
      structuredContent: {
        status: 'preview_ready',
        summary: { shipment_count: 2, total_charge: 18.44, currency: 'USD' },
      },
      content: [],
      meta: {
        execute_tool: 'execute_shipments',
        preview_ref: 'prv_123',
        execution_grant_ref: 'gr_openai_123',
      },
    });
  });

  it('calls MCP tools through tools/call from the widget', async () => {
    const fakeWindow = new FakeWindow();
    TestBed.configureTestingModule({
      providers: [{ provide: OPENAI_WINDOW, useValue: fakeWindow }],
    });

    const service = TestBed.inject(OpenAiHostBridgeService);
    const result = await service.callTool('execute_shipments', {
      preview_ref: 'prv_123',
      execution_grant_ref: 'gr_openai_123',
    });

    expect(fakeWindow.openai.tools.call).toHaveBeenCalledWith({
      name: 'execute_shipments',
      arguments: {
        preview_ref: 'prv_123',
        execution_grant_ref: 'gr_openai_123',
      },
    });
    expect(result.structuredContent).toEqual({
      status: 'running',
      job_ref: 'job_123',
    });
  });

  it('subscribes to MCP Apps tool-result notifications', () => {
    const fakeWindow = new FakeWindow();
    TestBed.configureTestingModule({
      providers: [{ provide: OPENAI_WINDOW, useValue: fakeWindow }],
    });

    const service = TestBed.inject(OpenAiHostBridgeService);
    const listener = vi.fn();
    const unsubscribe = service.subscribeToolResults(listener);

    fakeWindow.emitMessage({
      jsonrpc: '2.0',
      method: 'ui/notifications/tool-result',
      params: {
        structuredContent: { status: 'completed', job_ref: 'job_123' },
        content: [],
        _meta: { job_ref: 'job_123' },
      },
    });
    unsubscribe();
    fakeWindow.emitMessage({
      jsonrpc: '2.0',
      method: 'ui/notifications/tool-result',
      params: {
        structuredContent: { status: 'ignored' },
        content: [],
        _meta: {},
      },
    });

    expect(listener).toHaveBeenCalledTimes(1);
    expect(listener).toHaveBeenCalledWith({
      structuredContent: { status: 'completed', job_ref: 'job_123' },
      content: [],
      meta: { job_ref: 'job_123' },
    });
  });
});
```

- [ ] **Step 3: Run the failing bridge tests**

Run:

```bash
cd shipagent-frontend
npx nx test provider-widget -- --runTestsByPath apps/provider-widget/src/app/openai-host-bridge.service.spec.ts
```

Expected: FAIL because `openai-host-bridge.service.ts` does not exist.

- [ ] **Step 4: Implement the OpenAI host bridge**

Create `shipagent-frontend/apps/provider-widget/src/app/openai-host-bridge.service.ts`.

```typescript
import { Injectable, InjectionToken, inject } from '@angular/core';
import {
  OpenAiAppsWindow,
  OpenAiToolResult,
  WidgetActionMeta,
  WidgetStructuredContent,
} from './openai-widget.models';

export const OPENAI_WINDOW = new InjectionToken<OpenAiAppsWindow>(
  'ShipAgent OpenAI Apps window bridge',
  {
    providedIn: 'root',
    factory: () => window as unknown as OpenAiAppsWindow,
  },
);

@Injectable({ providedIn: 'root' })
export class OpenAiHostBridgeService {
  private readonly hostWindow = inject(OPENAI_WINDOW);

  readInitialToolResult(): OpenAiToolResult {
    const host = this.hostWindow.openai;
    const metadata = host?.toolResponseMetadata ?? null;
    const envelope = normalizeEnvelope(
      metadata?.mcp_tool_result ?? metadata?.call_tool_result ?? null,
    );
    if (envelope) {
      return envelope;
    }
    return {
      structuredContent: normalizeStructuredContent(host?.toolOutput ?? {}),
      content: [],
      meta: normalizeMeta(metadata?._meta ?? {}),
    };
  }

  async callTool(
    name: string,
    args: Record<string, unknown>,
  ): Promise<OpenAiToolResult> {
    const call = this.hostWindow.openai?.tools?.call;
    if (!call) {
      return {
        structuredContent: {
          status: 'unavailable',
          reason: 'widget_host_missing_tools_call',
          terminal: true,
          message: 'ChatGPT did not expose the widget tool-call bridge. Ask ShipAgent to continue in chat.',
        },
        content: [],
        meta: {},
      };
    }
    return normalizeEnvelope(await call({ name, arguments: args }));
  }

  subscribeToolResults(listener: (result: OpenAiToolResult) => void): () => void {
    const handler = (event: Event): void => {
      const data = (event as MessageEvent).data as {
        method?: string;
        params?: unknown;
      };
      if (data?.method !== 'ui/notifications/tool-result') {
        return;
      }
      listener(normalizeEnvelope(data.params));
    };
    this.hostWindow.addEventListener('message', handler);
    return () => this.hostWindow.removeEventListener('message', handler);
  }

  persistWidgetState(state: unknown): void {
    this.hostWindow.openai?.setWidgetState?.(state);
  }

  openDownload(url: string): void {
    this.hostWindow.open(url, '_blank', 'noopener,noreferrer');
  }
}

function normalizeEnvelope(value: unknown): OpenAiToolResult {
  const payload = isRecord(value) ? value : {};
  return {
    structuredContent: normalizeStructuredContent(
      payload['structuredContent'] ?? payload['structured_content'] ?? {},
    ),
    content: Array.isArray(payload['content']) ? payload['content'] : [],
    meta: normalizeMeta(payload['_meta'] ?? payload['meta'] ?? {}),
  };
}

function normalizeStructuredContent(value: unknown): WidgetStructuredContent {
  return isRecord(value) ? (value as WidgetStructuredContent) : {};
}

function normalizeMeta(value: unknown): WidgetActionMeta {
  return isRecord(value) ? (value as WidgetActionMeta) : {};
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
```

- [ ] **Step 5: Run the bridge tests**

Run:

```bash
cd shipagent-frontend
npx nx test provider-widget -- --runTestsByPath apps/provider-widget/src/app/openai-host-bridge.service.spec.ts
```

Expected: PASS.

- [ ] **Step 6: Commit the bridge**

```bash
git add shipagent-frontend/apps/provider-widget/src/app/openai-widget.models.ts shipagent-frontend/apps/provider-widget/src/app/openai-host-bridge.service.ts shipagent-frontend/apps/provider-widget/src/app/openai-host-bridge.service.spec.ts
git commit -m "feat: add OpenAI widget host bridge"
```

---

### Task 6: Add Widget State Reducers For Rates, Preview, Progress, And Labels

**Files:**

- Create: `shipagent-frontend/apps/provider-widget/src/app/openai-widget.state.ts`
- Create: `shipagent-frontend/apps/provider-widget/src/app/openai-widget.state.spec.ts`

- [ ] **Step 1: Write failing pure-state tests**

Create `shipagent-frontend/apps/provider-widget/src/app/openai-widget.state.spec.ts`.

```typescript
import { describe, expect, it } from 'vitest';
import {
  buildExecuteArguments,
  buildLabelArguments,
  buildStatusArguments,
  emptyWidgetState,
  hydrateWidgetState,
  isTerminalStatus,
} from './openai-widget.state';

describe('openai-widget.state', () => {
  it('hydrates rate options without recipient row details', () => {
    const state = hydrateWidgetState('rates', {
      structuredContent: {
        status: 'rates_ready',
        rates: [
          {
            id: 'ups_ground',
            carrier: 'UPS',
            service_name: 'Ground',
            total_charge: 12.34,
            currency: 'USD',
            selected: true,
          },
        ],
        selected: 'ups_ground',
      },
      content: [],
      meta: {},
    });

    expect(state.rateOptions).toHaveLength(1);
    expect(state.rateOptions[0].service_name).toBe('Ground');
    expect(JSON.stringify(state)).not.toContain('recipient_name');
  });

  it('builds execute arguments only from widget-private metadata', () => {
    const state = hydrateWidgetState('confirmation', {
      structuredContent: {
        status: 'preview_ready',
        summary: { shipment_count: 3, total_charge: 27.66, currency: 'USD' },
      },
      content: [],
      meta: {
        execute_tool: 'execute_shipments',
        preview_ref: 'prv_123',
        execution_grant_ref: 'gr_openai_123',
        idempotency_key: 'idem_123',
        selected_rate_id: 'ups_ground',
        authorized_amount: 27.66,
        currency: 'USD',
      },
    });

    expect(buildExecuteArguments(state)).toEqual({
      preview_ref: 'prv_123',
      execution_grant_ref: 'gr_openai_123',
      idempotency_key: 'idem_123',
      selected_rate_id: 'ups_ground',
      authorized_amount: 27.66,
      currency: 'USD',
    });
  });

  it('normalizes progress and label download arguments from job references', () => {
    const state = hydrateWidgetState('progress', {
      structuredContent: {
        status: 'running',
        job_ref: 'job_123',
        progress: { completed: 2, failed: 0, needs_review: 0, not_started: 1, total: 3 },
      },
      content: [],
      meta: {
        job_ref: 'job_123',
        get_job_status_tool: 'get_job_status',
        create_label_download_tool: 'create_label_download',
      },
    });

    expect(buildStatusArguments(state)).toEqual({ job_ref: 'job_123' });
    expect(buildLabelArguments(state)).toEqual({ job_ref: 'job_123' });
  });

  it('classifies terminal states for polling decisions', () => {
    expect(isTerminalStatus('completed')).toBe(true);
    expect(isTerminalStatus('needs_review')).toBe(true);
    expect(isTerminalStatus('preview_changed')).toBe(true);
    expect(isTerminalStatus('running')).toBe(false);
    expect(isTerminalStatus(undefined)).toBe(false);
  });

  it('creates a stable empty state for missing host data', () => {
    expect(emptyWidgetState('preview')).toMatchObject({
      mode: 'preview',
      status: 'waiting',
      rateOptions: [],
      summary: {},
      actionMeta: {},
    });
  });
});
```

- [ ] **Step 2: Run the failing pure-state tests**

Run:

```bash
cd shipagent-frontend
npx nx test provider-widget -- --runTestsByPath apps/provider-widget/src/app/openai-widget.state.spec.ts
```

Expected: FAIL because `openai-widget.state.ts` does not exist.

- [ ] **Step 3: Implement widget state reducers**

Create `shipagent-frontend/apps/provider-widget/src/app/openai-widget.state.ts`.

```typescript
import {
  OpenAiToolResult,
  RateOption,
  WidgetActionMeta,
  WidgetMode,
  WidgetStructuredContent,
  WidgetSummary,
} from './openai-widget.models';

export interface ProviderWidgetState {
  mode: WidgetMode;
  status: string;
  reason?: string;
  terminal: boolean;
  message?: string;
  summary: WidgetSummary;
  rateOptions: RateOption[];
  selectedRateId?: string;
  previewRef?: string;
  jobRef?: string;
  downloadUrl?: string;
  progress: {
    completed: number;
    failed: number;
    needsReview: number;
    notStarted: number;
    total: number;
  };
  actionMeta: WidgetActionMeta;
}

export function emptyWidgetState(mode: WidgetMode): ProviderWidgetState {
  return {
    mode,
    status: 'waiting',
    terminal: false,
    summary: {},
    rateOptions: [],
    progress: {
      completed: 0,
      failed: 0,
      needsReview: 0,
      notStarted: 0,
      total: 0,
    },
    actionMeta: {},
  };
}

export function hydrateWidgetState(
  mode: WidgetMode,
  result: OpenAiToolResult,
): ProviderWidgetState {
  const structured = result.structuredContent;
  const meta = result.meta;
  const jobRef = structured.job_ref ?? structured.job_id ?? meta.job_ref;
  const previewRef = structured.preview_ref ?? structured.preview_id ?? meta.preview_ref;
  return {
    mode,
    status: structured.status ?? 'ready',
    reason: structured.reason,
    terminal: structured.terminal ?? isTerminalStatus(structured.status),
    message: structured.message,
    summary: structured.summary ?? {},
    rateOptions: sanitizeRates(structured),
    selectedRateId: structured.selected ?? meta.selected_rate_id,
    previewRef,
    jobRef,
    downloadUrl: structured.download_url,
    progress: {
      completed: structured.progress?.completed ?? 0,
      failed: structured.progress?.failed ?? 0,
      needsReview: structured.progress?.needs_review ?? 0,
      notStarted: structured.progress?.not_started ?? 0,
      total: structured.progress?.total ?? 0,
    },
    actionMeta: meta,
  };
}

export function buildExecuteArguments(state: ProviderWidgetState): Record<string, unknown> {
  const meta = state.actionMeta;
  return compactArguments({
    preview_ref: meta.preview_ref ?? state.previewRef,
    execution_grant_ref: meta.execution_grant_ref,
    approval_request_ref: meta.approval_request_ref,
    idempotency_key: meta.idempotency_key,
    selected_rate_id: meta.selected_rate_id ?? state.selectedRateId,
    authorized_amount: meta.authorized_amount,
    currency: meta.currency ?? state.summary.currency,
  });
}

export function buildStatusArguments(state: ProviderWidgetState): Record<string, unknown> {
  return compactArguments({
    job_ref: state.actionMeta.job_ref ?? state.jobRef,
  });
}

export function buildLabelArguments(state: ProviderWidgetState): Record<string, unknown> {
  return compactArguments({
    job_ref: state.actionMeta.job_ref ?? state.jobRef,
  });
}

export function isTerminalStatus(status: string | undefined): boolean {
  return (
    status === 'completed' ||
    status === 'needs_review' ||
    status === 'failed' ||
    status === 'blocked' ||
    status === 'unavailable' ||
    status === 'preview_changed' ||
    status === 'approval_expired' ||
    status === 'approval_rejected'
  );
}

function sanitizeRates(content: WidgetStructuredContent): RateOption[] {
  return (content.rates ?? []).map((rate) => ({
    id: rate.id,
    carrier: rate.carrier,
    service: rate.service,
    service_name: rate.service_name,
    total_charge: rate.total_charge,
    currency: rate.currency,
    estimated_delivery: rate.estimated_delivery,
    selected: rate.selected ?? rate.id === content.selected,
  }));
}

function compactArguments(args: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(args).filter(([, value]) => value !== undefined && value !== null && value !== ''),
  );
}
```

- [ ] **Step 4: Run the pure-state tests**

Run:

```bash
cd shipagent-frontend
npx nx test provider-widget -- --runTestsByPath apps/provider-widget/src/app/openai-widget.state.spec.ts
```

Expected: PASS.

- [ ] **Step 5: Commit state reducers**

```bash
git add shipagent-frontend/apps/provider-widget/src/app/openai-widget.state.ts shipagent-frontend/apps/provider-widget/src/app/openai-widget.state.spec.ts
git commit -m "feat: model OpenAI widget state"
```

---

### Task 7: Build The Provider Widget Component

**Files:**

- Create: `shipagent-frontend/apps/provider-widget/src/app/provider-widget.component.ts`
- Create: `shipagent-frontend/apps/provider-widget/src/app/provider-widget.component.spec.ts`
- Modify: `shipagent-frontend/apps/provider-widget/src/main.ts`
- Modify: `shipagent-frontend/apps/provider-widget/src/styles.css`

- [ ] **Step 1: Write failing component tests**

Create `shipagent-frontend/apps/provider-widget/src/app/provider-widget.component.spec.ts`.

```typescript
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';
import { OpenAiHostBridgeService } from './openai-host-bridge.service';
import { ProviderWidgetComponent } from './provider-widget.component';

function createBridge() {
  return {
    readInitialToolResult: vi.fn().mockReturnValue({
      structuredContent: {
        status: 'preview_ready',
        summary: { shipment_count: 2, warning_count: 1, total_charge: 18.44, currency: 'USD' },
      },
      content: [],
      meta: {
        execute_tool: 'execute_shipments',
        preview_ref: 'prv_123',
        execution_grant_ref: 'gr_openai_123',
        idempotency_key: 'idem_123',
        authorized_amount: 18.44,
        currency: 'USD',
      },
    }),
    callTool: vi.fn(),
    subscribeToolResults: vi.fn().mockReturnValue(() => undefined),
    persistWidgetState: vi.fn(),
    openDownload: vi.fn(),
  };
}

async function render(mode = 'confirmation') {
  const bridge = createBridge();
  bridge.callTool.mockImplementation((name: string) => {
    if (name === 'execute_shipments') {
      return Promise.resolve({
        structuredContent: { status: 'running', job_ref: 'job_123' },
        content: [],
        meta: {
          job_ref: 'job_123',
          get_job_status_tool: 'get_job_status',
          create_label_download_tool: 'create_label_download',
        },
      });
    }
    if (name === 'create_label_download') {
      return Promise.resolve({
        structuredContent: { status: 'ready', job_ref: 'job_123', download_url: 'https://dev-mcp.shipagent.app/labels/ref_123' },
        content: [],
        meta: { label_download_ref: 'ldr_123' },
      });
    }
    return Promise.resolve({
      structuredContent: { status: 'completed', job_ref: 'job_123', progress: { completed: 2, failed: 0, needs_review: 0, not_started: 0, total: 2 } },
      content: [],
      meta: { job_ref: 'job_123' },
    });
  });

  await TestBed.configureTestingModule({
    imports: [ProviderWidgetComponent],
    providers: [{ provide: OpenAiHostBridgeService, useValue: bridge }],
  }).compileComponents();

  const fixture = TestBed.createComponent(ProviderWidgetComponent);
  fixture.componentRef.setInput('mode', mode);
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
  return { fixture, bridge };
}

describe('ProviderWidgetComponent', () => {
  it('renders immutable preview summary for confirmation mode', async () => {
    const { fixture } = await render('confirmation');
    const element = fixture.nativeElement as HTMLElement;

    expect(element.textContent).toContain('2 shipments');
    expect(element.textContent).toContain('$18.44');
    expect(element.querySelector('button[data-testid="execute-button"]')).not.toBeNull();
  });

  it('calls execute_shipments only from the explicit execute button gesture', async () => {
    const { fixture, bridge } = await render('confirmation');
    const button = fixture.nativeElement.querySelector('button[data-testid="execute-button"]') as HTMLButtonElement;

    button.click();
    await fixture.whenStable();

    expect(bridge.callTool).toHaveBeenCalledWith('execute_shipments', {
      preview_ref: 'prv_123',
      execution_grant_ref: 'gr_openai_123',
      idempotency_key: 'idem_123',
      authorized_amount: 18.44,
      currency: 'USD',
    });
  });

  it('renders label download action after a completed job', async () => {
    const { fixture, bridge } = await render('progress');
    fixture.componentInstance.applyToolResult({
      structuredContent: {
        status: 'completed',
        job_ref: 'job_123',
        progress: { completed: 2, failed: 0, needs_review: 0, not_started: 0, total: 2 },
      },
      content: [],
      meta: {
        job_ref: 'job_123',
        create_label_download_tool: 'create_label_download',
      },
    });
    fixture.detectChanges();

    const button = fixture.nativeElement.querySelector('button[data-testid="label-button"]') as HTMLButtonElement;
    button.click();
    await fixture.whenStable();
    fixture.detectChanges();

    expect(bridge.callTool).toHaveBeenCalledWith('create_label_download', { job_ref: 'job_123' });
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Download labels');
  });
});
```

- [ ] **Step 2: Run the failing component tests**

Run:

```bash
cd shipagent-frontend
npx nx test provider-widget -- --runTestsByPath apps/provider-widget/src/app/provider-widget.component.spec.ts
```

Expected: FAIL because `provider-widget.component.ts` does not exist.

- [ ] **Step 3: Implement the provider widget component**

Create `shipagent-frontend/apps/provider-widget/src/app/provider-widget.component.ts`.

```typescript
import { CommonModule, CurrencyPipe } from '@angular/common';
import { Component, OnDestroy, OnInit, computed, inject, input, signal } from '@angular/core';
import { OpenAiHostBridgeService } from './openai-host-bridge.service';
import { OpenAiToolResult, WidgetMode } from './openai-widget.models';
import {
  ProviderWidgetState,
  buildExecuteArguments,
  buildLabelArguments,
  buildStatusArguments,
  emptyWidgetState,
  hydrateWidgetState,
  isTerminalStatus,
} from './openai-widget.state';

@Component({
  selector: 'shipagent-provider-widget',
  standalone: true,
  imports: [CommonModule],
  providers: [CurrencyPipe],
  template: `
    <section class="widget-shell" [attr.data-mode]="mode()">
      <header class="widget-header">
        <div>
          <p class="eyebrow">ShipAgent</p>
          <h1>{{ title() }}</h1>
        </div>
        <span class="status-pill" [attr.data-status]="state().status">{{ statusLabel() }}</span>
      </header>

      <p class="message" *ngIf="state().message">{{ state().message }}</p>

      <section class="summary-grid" *ngIf="hasSummary()">
        <div>
          <span>Shipments</span>
          <strong>{{ state().summary.shipment_count ?? 0 }}</strong>
        </div>
        <div>
          <span>Warnings</span>
          <strong>{{ state().summary.warning_count ?? 0 }}</strong>
        </div>
        <div>
          <span>Total</span>
          <strong>{{ formatMoney(state().summary.total_charge, state().summary.currency) }}</strong>
        </div>
      </section>

      <section class="rates" *ngIf="state().rateOptions.length > 0">
        <article class="rate-row" *ngFor="let rate of state().rateOptions" [attr.data-selected]="rate.selected">
          <div>
            <strong>{{ rate.service_name || rate.service || 'Service' }}</strong>
            <span>{{ rate.carrier || 'Carrier' }}</span>
          </div>
          <span>{{ formatMoney(rate.total_charge, rate.currency) }}</span>
        </article>
      </section>

      <section class="progress" *ngIf="showProgress()">
        <div class="progress-bar">
          <span [style.width.%]="progressPercent()"></span>
        </div>
        <div class="progress-counts">
          <span>{{ state().progress.completed }} completed</span>
          <span>{{ state().progress.failed }} failed</span>
          <span>{{ state().progress.notStarted }} pending</span>
        </div>
      </section>

      <footer class="actions">
        <button
          type="button"
          data-testid="execute-button"
          *ngIf="showExecuteButton()"
          [disabled]="busy() || !canExecute()"
          (click)="executeShipments()"
        >
          Execute shipment purchase
        </button>

        <button
          type="button"
          data-testid="refresh-button"
          *ngIf="showRefreshButton()"
          [disabled]="busy() || !state().jobRef"
          (click)="refreshStatus()"
        >
          Refresh progress
        </button>

        <button
          type="button"
          data-testid="label-button"
          *ngIf="showLabelButton()"
          [disabled]="busy() || !state().jobRef"
          (click)="createLabelDownload()"
        >
          Create label download
        </button>

        <a
          class="download-link"
          *ngIf="state().downloadUrl"
          [href]="state().downloadUrl"
          target="_blank"
          rel="noopener noreferrer"
          (click)="openDownload($event)"
        >
          Download labels
        </a>
      </footer>
    </section>
  `,
})
export class ProviderWidgetComponent implements OnInit, OnDestroy {
  readonly mode = input<WidgetMode>('preview');

  private readonly bridge = inject(OpenAiHostBridgeService);
  private unsubscribeToolResults: (() => void) | undefined;

  readonly state = signal<ProviderWidgetState>(emptyWidgetState('preview'));
  readonly busy = signal(false);

  readonly title = computed(() => {
    switch (this.state().mode) {
      case 'rates':
        return 'Rates';
      case 'confirmation':
        return 'Confirm purchase';
      case 'progress':
        return 'Job progress';
      case 'labels':
        return 'Labels';
      default:
        return 'Shipment preview';
    }
  });

  readonly statusLabel = computed(() => this.state().status.replace(/_/g, ' '));
  readonly hasSummary = computed(() => Object.keys(this.state().summary).length > 0);
  readonly showProgress = computed(() => this.state().progress.total > 0 || this.state().jobRef !== undefined);
  readonly progressPercent = computed(() => {
    const progress = this.state().progress;
    if (progress.total <= 0) {
      return 0;
    }
    return Math.round((progress.completed / progress.total) * 100);
  });

  ngOnInit(): void {
    this.applyToolResult(this.bridge.readInitialToolResult());
    this.unsubscribeToolResults = this.bridge.subscribeToolResults((result) => {
      this.applyToolResult(result);
    });
  }

  ngOnDestroy(): void {
    this.unsubscribeToolResults?.();
  }

  applyToolResult(result: OpenAiToolResult): void {
    this.state.set(hydrateWidgetState(this.mode(), result));
    this.bridge.persistWidgetState(this.state());
  }

  async executeShipments(): Promise<void> {
    if (!this.canExecute()) {
      return;
    }
    await this.callAndApply(
      this.state().actionMeta.execute_tool ?? 'execute_shipments',
      buildExecuteArguments(this.state()),
    );
  }

  async refreshStatus(): Promise<void> {
    await this.callAndApply(
      this.state().actionMeta.get_job_status_tool ?? 'get_job_status',
      buildStatusArguments(this.state()),
    );
  }

  async createLabelDownload(): Promise<void> {
    await this.callAndApply(
      this.state().actionMeta.create_label_download_tool ?? 'create_label_download',
      buildLabelArguments(this.state()),
    );
  }

  openDownload(event: Event): void {
    const url = this.state().downloadUrl;
    if (!url) {
      return;
    }
    event.preventDefault();
    this.bridge.openDownload(url);
  }

  showExecuteButton(): boolean {
    return this.state().mode === 'confirmation' || this.state().mode === 'preview';
  }

  showRefreshButton(): boolean {
    return this.state().jobRef !== undefined && !isTerminalStatus(this.state().status);
  }

  showLabelButton(): boolean {
    return this.state().jobRef !== undefined && this.state().status === 'completed' && !this.state().downloadUrl;
  }

  canExecute(): boolean {
    const args = buildExecuteArguments(this.state());
    return args['preview_ref'] !== undefined && args['execution_grant_ref'] !== undefined;
  }

  formatMoney(amount: number | undefined, currency: string | undefined): string {
    if (amount === undefined) {
      return 'Not priced';
    }
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: currency ?? 'USD',
    }).format(amount);
  }

  private async callAndApply(name: string, args: Record<string, unknown>): Promise<void> {
    this.busy.set(true);
    try {
      this.applyToolResult(await this.bridge.callTool(name, args));
    } finally {
      this.busy.set(false);
    }
  }
}
```

- [ ] **Step 4: Update the custom element bootstrap**

Replace `shipagent-frontend/apps/provider-widget/src/main.ts` with:

```typescript
import { createApplication } from '@angular/platform-browser';
import { createCustomElement } from '@angular/elements';
import { ProviderWidgetComponent } from './app/provider-widget.component';

const tagName = 'shipagent-provider-widget';

createApplication()
  .then((appRef) => {
    if (!customElements.get(tagName)) {
      const element = createCustomElement(ProviderWidgetComponent, {
        injector: appRef.injector,
      });
      customElements.define(tagName, element);
    }
  })
  .catch((err) => console.error(err));
```

- [ ] **Step 5: Replace provider-widget styles**

Replace `shipagent-frontend/apps/provider-widget/src/styles.css` with:

```css
:root {
  color: #111827;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.4;
}

* {
  box-sizing: border-box;
}

html,
body {
  margin: 0;
  min-width: 320px;
  background: #ffffff;
}

button,
a {
  font: inherit;
}

.widget-shell {
  display: grid;
  gap: 14px;
  padding: 16px;
  color: #111827;
}

.widget-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.eyebrow {
  margin: 0 0 2px;
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
}

h1 {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  letter-spacing: 0;
}

.status-pill {
  border: 1px solid #cbd5e1;
  border-radius: 999px;
  padding: 4px 8px;
  color: #334155;
  font-size: 12px;
  white-space: nowrap;
}

.message {
  margin: 0;
  color: #475569;
  font-size: 14px;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.summary-grid div {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px;
}

.summary-grid span,
.rate-row span,
.progress-counts {
  color: #64748b;
  font-size: 12px;
}

.summary-grid strong {
  display: block;
  margin-top: 4px;
  font-size: 16px;
}

.rates {
  display: grid;
  gap: 8px;
}

.rate-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px;
}

.rate-row[data-selected="true"] {
  border-color: #2563eb;
  background: #eff6ff;
}

.rate-row strong,
.rate-row span {
  display: block;
}

.progress {
  display: grid;
  gap: 8px;
}

.progress-bar {
  overflow: hidden;
  height: 8px;
  border-radius: 999px;
  background: #e2e8f0;
}

.progress-bar span {
  display: block;
  height: 100%;
  background: #0f766e;
}

.progress-counts {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

button,
.download-link {
  min-height: 36px;
  border-radius: 8px;
  padding: 8px 12px;
  font-weight: 700;
  text-decoration: none;
}

button {
  border: 1px solid #0f172a;
  background: #0f172a;
  color: #ffffff;
  cursor: pointer;
}

button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.download-link {
  display: inline-flex;
  align-items: center;
  border: 1px solid #0f766e;
  color: #0f766e;
}
```

- [ ] **Step 6: Run the component tests**

Run:

```bash
cd shipagent-frontend
npx nx test provider-widget -- --runTestsByPath apps/provider-widget/src/app/provider-widget.component.spec.ts
```

Expected: PASS.

- [ ] **Step 7: Run all provider-widget tests**

Run:

```bash
cd shipagent-frontend
npx nx test provider-widget
```

Expected: PASS.

- [ ] **Step 8: Commit the component**

```bash
git add shipagent-frontend/apps/provider-widget/src/app/provider-widget.component.ts shipagent-frontend/apps/provider-widget/src/app/provider-widget.component.spec.ts shipagent-frontend/apps/provider-widget/src/main.ts shipagent-frontend/apps/provider-widget/src/styles.css
git commit -m "feat: build OpenAI provider widget"
```

---

### Task 8: Lock OpenAI Descriptor And Widget Privacy Contracts

**Files:**

- Modify: `tests/provider_adapters/test_projections.py`
- Test: `tests/provider_adapters/test_projections.py`
- Test: `tests/hosted/test_openai_widget_resources.py`
- Test: `tests/registry/test_artifact_drift.py`

- [ ] **Step 1: Add descriptor privacy regression tests**

Append these tests to `tests/provider_adapters/test_projections.py`.

```python
def test_openai_execute_is_widget_only_and_keeps_confirmation_resource():
    descriptor = to_openai_app_tool(tool("execute_shipments"))

    assert descriptor["_meta"]["ui"]["resourceUri"] == "ui://shipagent/confirmation.html"
    assert descriptor["_meta"]["ui"]["visibility"] == ["app"]


def test_openai_preview_and_progress_resources_are_model_visible_widgets():
    preview = to_openai_app_tool(tool("prepare_shipments"))
    progress = to_openai_app_tool(tool("get_job_status"))

    assert preview["_meta"]["ui"]["resourceUri"] == "ui://shipagent/preview.html"
    assert progress["_meta"]["ui"]["resourceUri"] == "ui://shipagent/progress.html"
    assert "visibility" not in preview["_meta"]["ui"]
    assert "visibility" not in progress["_meta"]["ui"]
```

- [ ] **Step 2: Run descriptor regression tests**

Run:

```bash
.venv/bin/python -m pytest tests/provider_adapters/test_projections.py -v -k "openai_execute_is_widget_only or preview_and_progress"
```

Expected: PASS after Plan 6 descriptor visibility work has landed. If this fails because `provider_descriptor_visibility` does not exist, finish Plan 6 before continuing Plan 8.

- [ ] **Step 3: Run resource and artifact drift tests**

Run:

```bash
.venv/bin/python -m pytest tests/hosted/test_openai_widget_resources.py tests/registry/test_artifact_drift.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit descriptor regressions**

```bash
git add tests/provider_adapters/test_projections.py
git commit -m "test: lock OpenAI widget descriptor contracts"
```

---

### Task 9: Full Plan 8 Verification

**Files:**

- No source edits in this task

- [ ] **Step 1: Run focused backend widget/resource tests**

Run:

```bash
.venv/bin/python -m pytest tests/hosted/test_openai_widget_resources.py tests/registry/test_openai_widget_ui_resources.py tests/provider_adapters/test_projections.py tests/control_plane/test_app_auth.py -v -k "widget or openai"
```

Expected: PASS.

- [ ] **Step 2: Run registry drift validation**

Run:

```bash
.venv/bin/python -m pytest tests/registry/test_artifact_drift.py -v
```

Expected: PASS.

- [ ] **Step 3: Run provider-widget frontend validation**

Run:

```bash
cd shipagent-frontend
npx nx typecheck provider-widget
npx nx test provider-widget
npx nx build provider-widget --configuration=production
```

Expected: all three commands PASS, and `shipagent-frontend/dist/apps/provider-widget/browser/main.js` plus `styles.css` exist.

- [ ] **Step 4: Verify resource HTML points at the built widget bundle**

Run:

```bash
test -f shipagent-frontend/dist/apps/provider-widget/browser/main.js
test -f shipagent-frontend/dist/apps/provider-widget/browser/styles.css
```

Expected: both commands exit 0.

- [ ] **Step 5: Run broader backend validation for touched areas**

Run:

```bash
.venv/bin/python -m pytest tests/hosted tests/registry tests/provider_adapters tests/control_plane -v
.venv/bin/python -m ruff check src/ tests/
```

Expected: PASS.

- [ ] **Step 6: Run frontend affected validation**

Run:

```bash
cd shipagent-frontend
npx nx run-many -t typecheck test build --projects=provider-widget --configuration=production
```

Expected: PASS.

- [ ] **Step 7: Commit verification-only fixes if formatting or generated files changed**

Run this only if `git status --short` shows formatting or generated artifact changes from the verification commands:

```bash
git add src/ tests/ shipagent-frontend/apps/provider-widget generated/provider_artifacts
git commit -m "chore: verify OpenAI widget integration"
```

Expected: commit created only when the verification commands changed files.

---

## Dependencies Consumed And Provided

Consumed from Plan 6:

- `execute_shipments` projected to OpenAI with `_meta.ui.visibility: ["app"]`.
- OpenAI model-visible structured content stays aggregate-only for local-source data.
- `OPENAI_WIDGET_META` is delivered in tool result `_meta`, never in model-visible content.
- Public schemas and scopes use the Plan 6 naming after it lands. If Plan 6 renames `job_id` to `job_ref`, use `job_ref` in widget calls and keep the compatibility reads in the widget state reducer.

Consumed from Plan 7:

- `prepare_shipments` returns preview structured content plus widget-private execute metadata.
- `execute_shipments` accepts widget-private OpenAI grant/reference arguments and returns `job_ref`.
- `get_job_status` accepts `job_ref` and returns aggregate progress counts.
- `create_label_download` accepts `job_ref` and returns a browser-authenticated label download URL or reference.
- Label bytes are never returned to the widget; only an authenticated browser action is exposed.

Provided to Plan 10:

- A concrete OpenAI widget UI to exercise in developer mode.
- Resource registration tests proving every OpenAI `ui_resource` is served as `text/html;profile=mcp-app`.
- Component tests for explicit execute-button confirmation, progress, and label action.
- Descriptor tests proving `execute_shipments` is app-only while preview/progress widgets remain model-visible resources.

## Overlap Risks

- Plan 6 also edits `src/registry/tools/public.py`, `src/provider_adapters/openai_projection.py`, and generated artifacts. Run Plan 8 after Plan 6 and keep Plan 8 registry edits limited to `ui_resource` values for progress and labels.
- Plan 7 owns execution handlers, approval/grant validation, job lifecycle, and label reference streaming. Plan 8 must not implement grant persistence, shipment execution, polling services, or label bytes.
- Plan 10 owns adversarial prompt and developer-mode corpus coverage. Plan 8 adds focused unit/contract tests only, leaving prompt suites and MCP Inspector scripts to Plan 10.
- `tests/provider_adapters/test_projections.py` is touched by Plans 6 and 8. Rebase Plan 8 after Plan 6, then add only the descriptor tests listed here.

## Validation Commands

Backend:

```bash
.venv/bin/python -m pytest tests/hosted/test_openai_widget_resources.py tests/registry/test_openai_widget_ui_resources.py tests/provider_adapters/test_projections.py tests/control_plane/test_app_auth.py -v -k "widget or openai"
.venv/bin/python -m pytest tests/registry/test_artifact_drift.py -v
.venv/bin/python -m pytest tests/hosted tests/registry tests/provider_adapters tests/control_plane -v
.venv/bin/python -m ruff check src/ tests/
```

Frontend:

```bash
cd shipagent-frontend
npx nx typecheck provider-widget
npx nx test provider-widget
npx nx build provider-widget --configuration=production
```

Provider artifacts:

```bash
.venv/bin/python scripts/generate_provider_artifacts.py
.venv/bin/python -m pytest tests/registry/test_artifact_drift.py -v
```

## Self-Review Checklist

- Spec coverage: Tasks 1 and 3 cover MCP Apps HTML resources and first-party widget asset serving. Task 2 covers `ui_resource` fields. Tasks 5 through 7 cover rates, preview/confirm, execute button gesture, job progress, label download action, and widget-only metadata. Task 8 covers OpenAI widget visibility and descriptor privacy. Task 9 covers the testing strategy.
- Placeholder scan: Every task has exact files, commands, expected outcomes, and concrete code snippets for code-changing steps.
- Type consistency: `WidgetMode`, `OpenAiToolResult`, `WidgetActionMeta`, `ProviderWidgetState`, `OpenAiHostBridgeService`, and `ProviderWidgetComponent` are defined before later tasks use them.
