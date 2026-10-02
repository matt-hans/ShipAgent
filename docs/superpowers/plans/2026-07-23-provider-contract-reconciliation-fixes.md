# Provider Contract Reconciliation Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct every security, migration, privacy-projection, and registry-test defect found while reviewing the provider-contract control-plane branch.

**Architecture:** Keep security validation independent from optional control-plane runtime availability, generate PostgreSQL-compatible DDL, require recursively closed aggregate result schemas, and retain intentional public exports through explicit per-tool opt-in. Canonical registry sources remain authoritative and generated provider artifacts are regenerated from them.

**Tech Stack:** Python 3.12, Pydantic, SQLAlchemy/Alembic, JSON Schema/jsonschema, pytest.

## Global Constraints

- Public `fake_local` authentication must never start outside local loopback mode, even when database and Redis URLs are absent.
- PostgreSQL Boolean defaults must compile to `false`, not integer `0`.
- Aggregate provider results must not admit arbitrary object properties at any nesting level.
- Public provider export must be an explicit per-tool opt-in; private tools remain non-exportable.
- Edit canonical registry sources and regenerate `generated/provider_artifacts/`; do not hand-edit generated artifacts.
- Follow vertical TDD: one failing behavioral test, minimal implementation, then green before the next task.

---

### Task 1: Preserve `fake_local` Security Without Runtime URLs

**Files:**
- Modify: `tests/control_plane/test_startup.py`
- Modify: `src/control_plane/startup.py`

**Interfaces:**
- Consumes: `validate_startup_security(settings: ControlPlaneSettings) -> None`
- Produces: the same interface, with loopback/local validation independent of database and Redis URL presence.

- [ ] **Step 1: Write the failing behavioral test**

Add a parametrized test proving that missing runtime URLs do not bypass each public/deployed restriction:

```python
@pytest.mark.parametrize(
    "overrides",
    [
        {"bind_host": "0.0.0.0"},
        {"public_base_url": "https://relay.example.com"},
        {"environment": Environment.production},
    ],
)
def test_validate_startup_security_rejects_insecure_fake_local_without_runtime_urls(
    overrides,
):
    with pytest.raises(RuntimeError, match="loopback"):
        validate_startup_security(
            mk_settings(database_url=None, redis_url=None, **overrides)
        )
```

- [ ] **Step 2: Run the test to verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_startup.py::test_validate_startup_security_rejects_insecure_fake_local_without_runtime_urls -v
```

Expected: all parameter cases fail because the current early return suppresses validation.

- [ ] **Step 3: Implement the minimal security fix**

Remove the URL-dependent early return. Retain the existing `auth_mode != AuthMode.fake_local` return, then enforce local environment, loopback bind host, and loopback public URL for every `fake_local` configuration.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_startup.py tests/control_plane/test_config.py -v
```

Expected: all tests pass, including the safe missing-runtime-URLs case.

- [ ] **Step 5: Commit**

```bash
git add src/control_plane/startup.py tests/control_plane/test_startup.py
git commit -m "fix: preserve fake-local startup security"
```

### Task 2: Generate PostgreSQL-Compatible Boolean DDL

**Files:**
- Modify: `tests/control_plane/test_migrations_postgres.py`
- Modify: `alembic/versions/20260609_0001_control_plane_core.py`

**Interfaces:**
- Consumes: Alembic revision `20260609_0001`
- Produces: PostgreSQL offline and online DDL using the Boolean literal `false`.

- [ ] **Step 1: Write the failing behavioral test**

Add an environment-isolated offline migration test that calls Alembic’s public command API and checks the generated PostgreSQL DDL:

```python
def test_postgres_migration_uses_boolean_false_default(monkeypatch, capsys):
    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    monkeypatch.setenv(
        "SHIPAGENT_DATABASE_URL",
        "postgresql+asyncpg://user:password@localhost/shipagent",
    )
    monkeypatch.setenv("SHIPAGENT_CONTROL_PLANE_SCHEMA", "shipagent_test")

    command.upgrade(config, "head", sql=True)

    sql = capsys.readouterr().out.lower()
    assert "suspended boolean default false not null" in " ".join(sql.split())
    assert "suspended boolean default 0 not null" not in " ".join(sql.split())
```

- [ ] **Step 2: Run the test to verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_migrations_postgres.py::test_postgres_migration_uses_boolean_false_default -v
```

Expected: FAIL because generated DDL contains `DEFAULT 0`.

- [ ] **Step 3: Implement the minimal migration fix**

Change the `suspended` column default to:

```python
server_default=sa.false()
```

- [ ] **Step 4: Run focused tests to verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_migrations_postgres.py -v
```

Expected: offline test passes; live PostgreSQL test passes when configured or skips when unavailable.

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/20260609_0001_control_plane_core.py tests/control_plane/test_migrations_postgres.py
git commit -m "fix: emit valid PostgreSQL boolean defaults"
```

### Task 3: Close Nested Aggregate Rate Results

**Files:**
- Modify: `tests/control_plane/test_result_projection.py`
- Modify: `tests/registry/test_catalog.py`
- Modify: `src/control_plane/result_projection.py`
- Modify: `src/registry/tools/public.py`
- Regenerate: `generated/provider_artifacts/*.json`

**Interfaces:**
- Consumes: `project_result(contract: ToolContract, result: dict) -> dict`
- Produces: recursively closed schemas for aggregate object values, including rate items with `service_code`, `service_name`, `total_charge`, `currency_code`, and optional `estimated_delivery_date`.

- [ ] **Step 1: Write the first failing behavioral test**

Add a projection test with an aggregate array whose item schema is an open object:

```python
def test_project_result_rejects_open_object_schema_inside_array():
    contract = _contract(
        output_schema={
            "type": "object",
            "properties": {
                "rates": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["rates"],
            "additionalProperties": False,
        }
    )

    with pytest.raises(ValueError, match="additionalProperties=False"):
        project_result(contract, {"rates": [{"customer_payload": "private"}]})
```

- [ ] **Step 2: Run the first test to verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_result_projection.py::test_project_result_rejects_open_object_schema_inside_array -v
```

Expected: FAIL because an object schema without `properties` currently returns successfully.

- [ ] **Step 3: Implement the minimal recursive closure fix**

In `_assert_closed_profile_schema_allowed`, when `value` is a dictionary, require `additionalProperties is False` before inspecting properties. Treat absent properties as an empty mapping so any actual key is rejected.

- [ ] **Step 4: Verify the first test is GREEN**

Run the same focused test. Expected: PASS.

- [ ] **Step 5: Write the second failing catalog test**

Add a catalog test that projects a safe rate and rejects an undeclared field:

```python
def test_rate_results_use_closed_provider_safe_items():
    tool = next(tool for tool in public_tools() if tool.name == "get_shipment_rates")
    item_schema = tool.output_schema["properties"]["rates"]["items"]

    assert item_schema["additionalProperties"] is False
    assert set(item_schema["properties"]) == {
        "service_code",
        "service_name",
        "total_charge",
        "currency_code",
        "estimated_delivery_date",
    }
```

- [ ] **Step 6: Run the second test to verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/registry/test_catalog.py::test_rate_results_use_closed_provider_safe_items -v
```

Expected: FAIL because rate items are currently open objects.

- [ ] **Step 7: Implement the closed canonical rate schema**

Replace the rate item schema with:

```python
object_schema(
    {
        "service_code": {"type": "string"},
        "service_name": {"type": "string"},
        "total_charge": {"type": "string"},
        "currency_code": {"type": "string"},
        "estimated_delivery_date": {"type": "string"},
    },
    ["service_code", "service_name", "total_charge", "currency_code"],
)
```

Then regenerate provider artifacts:

```bash
.venv/bin/python scripts/generate_provider_artifacts.py
```

- [ ] **Step 8: Run focused tests to verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_result_projection.py tests/registry/test_catalog.py tests/registry/test_artifact_drift.py tests/provider_adapters/test_projections.py -v
```

Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
git add src/control_plane/result_projection.py src/registry/tools/public.py tests/control_plane/test_result_projection.py tests/registry/test_catalog.py generated/provider_artifacts
git commit -m "fix: close aggregate rate result schemas"
```

### Task 4: Make Public Provider Export an Explicit Opt-In

**Files:**
- Modify: `src/registry/tools/public.py`
- Modify: `tests/registry/test_catalog.py`

**Interfaces:**
- Consumes: `public_tool(..., provider_export_enabled: bool = False) -> ToolContract`
- Produces: all eight intended public tools explicitly set `provider_export_enabled=True`; omitted values remain disabled.

- [ ] **Step 1: Use the existing failing registry test as RED**

Run:

```bash
.venv/bin/python -m pytest tests/registry/test_catalog.py::test_public_tools_are_tenant_safe_and_provider_exportable -v
```

Expected: FAIL because exported public tools are enabled while the assertion still expects `False`.

- [ ] **Step 2: Strengthen the behavioral test**

Change the assertion for catalog tools to:

```python
assert tool.provider_export_enabled is True
```

Add a test proving the helper default remains safe:

```python
def test_public_tool_requires_explicit_provider_export_opt_in():
    signature = inspect.signature(public_tool)
    assert signature.parameters["provider_export_enabled"].default is False
```

The new default-safety test must fail before production changes.

- [ ] **Step 3: Run the default-safety test to verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/registry/test_catalog.py::test_public_tool_requires_explicit_provider_export_opt_in -v
```

Expected: FAIL because the helper currently defaults to `True`.

- [ ] **Step 4: Implement explicit opt-in**

Change the helper default to `False` and pass:

```python
provider_export_enabled=True
```

in each of the eight `PUBLIC_TOOLS` declarations.

- [ ] **Step 5: Run focused tests to verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/registry/test_catalog.py tests/registry/test_export.py tests/provider_adapters/test_projections.py tests/e2e/test_portability_smoke.py -v
```

Expected: all tests pass and public generated exports remain non-empty.

- [ ] **Step 6: Regenerate artifacts and verify drift**

Run:

```bash
.venv/bin/python scripts/generate_provider_artifacts.py
.venv/bin/python -m pytest tests/registry/test_artifact_drift.py -v
```

Expected: artifact drift test passes; generated content is unchanged except for Task 3’s closed rate schema.

- [ ] **Step 7: Commit**

```bash
git add src/registry/tools/public.py tests/registry/test_catalog.py generated/provider_artifacts
git commit -m "fix: require explicit public provider exports"
```
