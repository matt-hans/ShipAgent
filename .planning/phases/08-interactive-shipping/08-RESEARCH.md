# Phase 8: Interactive Shipping - Research

**Researched:** 2026-02-12
**Domain:** Conversational single-shipment creation, MCP elicitation, dynamic form rendering
**Confidence:** HIGH

## Summary

Phase 8 adds the ability for users to create individual shipments through conversation without needing a data source file. The user says something like "Ship a 5lb box to John Smith at 123 Main St, NY 10001" and the system extracts available fields, prompts only for missing ones via a dynamic form, then creates the shipment.

The core pattern is: NL command -> intent parser extracts partial data -> deterministic schema generator computes missing fields -> frontend renders dynamic form from flat JSON Schema -> user fills form -> backend creates single-row job -> UPS API call -> label returned.

**Primary recommendation:** Extend the existing `ShippingIntent` model with `is_interactive` and `initial_data`, create a deterministic `ShippingFormSchemaGenerator` that compares provided vs required UPS fields, render forms on the frontend with a new `DynamicFormRenderer` component using manual shadcn/ui inputs (no external JSON Schema form library needed given the flat schema constraint), and route interactive shipments through the existing `BatchEngine` with a single-row job.

## Standard Stack

### Core (Already in Project)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | existing | REST API for interactive shipping endpoints | Already used |
| SQLAlchemy | existing | Job/JobRow persistence for single-shipment jobs | Already used |
| Pydantic | existing | Schema validation for form data and API contracts | Already used |
| React + TypeScript | existing | Frontend form rendering | Already used |
| shadcn/ui (manual) | existing | Form input components (Input, Select, Button) | Already used (manual copies) |
| UPSService | existing | Direct Python import for shipment creation | Already used by BatchEngine |

### Supporting (New, Minimal)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| None required | - | The flat JSON Schema from MCP spec is simple enough to render with existing shadcn components | - |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Manual form rendering | @rjsf/shadcn (react-jsonschema-form with shadcn theme) | Adds ~50KB dependency for a form with ~8 flat fields; manual rendering is simpler and matches project convention of no unnecessary deps |
| LLM-driven schema generation | Deterministic code-driven schema | LLM uses tokens and is non-deterministic; requirement INT-07 mandates <500 tokens, so code-driven is required |

**Installation:**
```bash
# No new packages needed - all components exist in project
```

## Architecture Patterns

### Recommended Project Structure
```
src/
├── services/
│   ├── interactive_shipping.py    # NEW: ShippingFormSchemaGenerator + InteractiveShippingService
│   ├── ups_payload_builder.py     # EXISTING: build_shipment_request() reused
│   ├── batch_engine.py            # EXISTING: single-row preview + execute
│   └── command_processor.py       # MODIFY: add interactive shipping path
├── api/
│   ├── routes/
│   │   └── commands.py            # MODIFY: handle interactive command flow
│   └── schemas.py                 # MODIFY: add InteractiveShipRequest/Response schemas
├── orchestrator/
│   ├── models/
│   │   └── intent.py              # MODIFY: add is_interactive + initial_data fields
│   └── nl_engine/
│       ├── intent_parser.py       # MODIFY: recognize interactive commands
│       └── elicitation.py         # MODIFY: transition to JSON Schema format
frontend/
├── src/
│   ├── components/
│   │   ├── CommandCenter.tsx       # MODIFY: handle 'elicit' action + form rendering
│   │   └── DynamicFormRenderer.tsx # NEW: renders flat JSON Schema as form inputs
│   ├── types/
│   │   └── api.ts                 # MODIFY: add interactive shipping types
│   └── lib/
│       └── api.ts                 # MODIFY: add submitInteractiveForm endpoint
```

### Pattern 1: Deterministic Schema Gap Analysis
**What:** Compare user-provided fields against UPS-required fields to generate a flat JSON Schema for the missing ones.
**When to use:** Every interactive shipping command.
**Example:**
```python
# Source: Deterministic, no LLM needed
# UPS required fields for domestic shipment
REQUIRED_FIELDS = {
    "ship_to_name": {"type": "string", "title": "Recipient Name"},
    "ship_to_address1": {"type": "string", "title": "Street Address"},
    "ship_to_city": {"type": "string", "title": "City"},
    "ship_to_state": {"type": "string", "title": "State", "maxLength": 2},
    "ship_to_postal_code": {"type": "string", "title": "ZIP Code", "pattern": "^\\d{5}(-\\d{4})?$"},
    "ship_to_country": {"type": "string", "title": "Country", "default": "US"},
    "weight": {"type": "number", "title": "Package Weight (lbs)", "minimum": 0.1, "maximum": 150},
    "service_code": {
        "type": "string",
        "title": "Shipping Service",
        "oneOf": [
            {"const": "03", "title": "UPS Ground (3-5 days)"},
            {"const": "02", "title": "2nd Day Air"},
            {"const": "01", "title": "Next Day Air"},
            {"const": "12", "title": "3 Day Select"},
            {"const": "13", "title": "Next Day Air Saver"},
        ],
        "default": "03",
    },
}

OPTIONAL_FIELDS = {
    "ship_to_address2": {"type": "string", "title": "Address Line 2"},
    "ship_to_phone": {"type": "string", "title": "Phone Number"},
    "ship_to_company": {"type": "string", "title": "Company Name"},
    "length": {"type": "number", "title": "Length (in)", "minimum": 1},
    "width": {"type": "number", "title": "Width (in)", "minimum": 1},
    "height": {"type": "number", "title": "Height (in)", "minimum": 1},
    "packaging_type": {
        "type": "string",
        "title": "Packaging Type",
        "oneOf": [
            {"const": "02", "title": "Customer Supplied Package"},
            {"const": "01", "title": "UPS Letter"},
            {"const": "03", "title": "Tube"},
            {"const": "04", "title": "PAK"},
        ],
        "default": "02",
    },
}

def generate_form_schema(provided_data: dict) -> dict:
    """Generate MCP-compliant flat JSON Schema for missing fields."""
    properties = {}
    required = []

    for field_name, field_schema in REQUIRED_FIELDS.items():
        if field_name not in provided_data or not provided_data[field_name]:
            properties[field_name] = field_schema
            required.append(field_name)

    # Always include optional fields (pre-populated if provided)
    for field_name, field_schema in OPTIONAL_FIELDS.items():
        if field_name not in provided_data:
            properties[field_name] = field_schema

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }
```

### Pattern 2: Intent Parser Interactive Detection
**What:** The LLM-based intent parser detects when a command is a direct shipping instruction (no data source reference) and sets `is_interactive=True`.
**When to use:** When user says "Ship a box to..." or "Send a package to..." without referencing a file/Shopify.
**Example:**
```python
# Added to ShippingIntent model
class ShippingIntent(BaseModel):
    action: Literal["ship", "rate", "validate_address"] = "ship"
    is_interactive: bool = False  # NEW: True when no data source referenced
    initial_data: dict | None = None  # NEW: Partial data extracted from NL command
    data_source: str | None = None
    service_code: ServiceCode | None = None
    # ... existing fields
```

### Pattern 3: Frontend Form-in-Chat Flow
**What:** The form appears inline in the chat conversation, following the same card pattern as PreviewCard.
**When to use:** When backend returns an `elicit` action with a JSON Schema.
**Example flow:**
1. User types: "Ship a 5lb box to John Smith at 123 Main St, New York NY 10001"
2. System message: "I found most details. Please confirm or fill in the remaining fields:"
3. DynamicFormRenderer appears inline with pre-filled fields + empty fields for missing data
4. User fills remaining fields (e.g., service level) and clicks "Ship" or "Cancel"
5. Backend creates single-row job, calls UPS, returns tracking + label

### Pattern 4: Single-Row Job Reuse
**What:** Interactive shipments create a standard Job with 1 JobRow, reusing the entire BatchEngine pipeline.
**When to use:** Every interactive shipment.
**Why:** Avoids duplicating shipment creation logic; the CompletionArtifact, label storage, and SSE progress all work without modification.

### Anti-Patterns to Avoid
- **LLM for schema generation:** The schema is fully deterministic (compare fields). Using an LLM wastes tokens and introduces non-determinism. Requirement INT-07 mandates <500 tokens.
- **Nested JSON Schema:** MCP elicitation spec restricts to flat objects with primitive properties only. Do not use nested objects, arrays of objects, or complex schema features.
- **Separate shipment creation path:** Do NOT bypass BatchEngine for interactive shipments. Create a single-row job and use the same preview/execute/label flow. This ensures audit trails, crash recovery, and label storage all work identically.
- **Requiring a data source for interactive mode:** The whole point is no data source needed. The `CommandProcessor._process_internal()` must route to a new interactive path when no data source is connected AND the intent is interactive.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| UPS payload construction | Custom payload builder for interactive mode | `build_shipment_request()` from `ups_payload_builder.py` | Already handles all edge cases (phone normalization, zip formatting, address truncation) |
| Shipment execution | Direct UPS API calls | `BatchEngine.execute()` with single-row job | Gets audit logging, label saving, SSE progress, crash recovery for free |
| Service code resolution | New service code mapping | `resolve_service_code()` from `ups_payload_builder.py` | Already maps names to codes |
| Form validation | Custom validation logic | JSON Schema `required` + `pattern` + `minimum`/`maximum` | Browser-side validation from schema, server-side Pydantic validation |
| Job state management | New job lifecycle | Existing `Job` + `JobRow` models | Single-row jobs work with existing state machine |

**Key insight:** Interactive shipping is NOT a new execution path -- it is a new INPUT path that feeds into the existing execution pipeline. The only new logic is: (1) detecting interactive intent, (2) extracting partial data from NL, (3) generating the form schema, (4) rendering the form, and (5) creating the single-row job from form data.

## Common Pitfalls

### Pitfall 1: Trying to Use LLM for Field Extraction AND Schema Generation
**What goes wrong:** Burning LLM tokens on both parsing the command AND generating the form schema.
**Why it happens:** Seems natural to have the LLM do everything.
**How to avoid:** The LLM ONLY parses the intent and extracts `initial_data` (the fields it can identify from the NL command). Schema generation is pure Python code that diffs provided vs required fields. Total LLM usage should be the single `parse_intent()` call (~200-400 tokens).
**Warning signs:** Token count exceeding 500 per interactive flow.

### Pitfall 2: Breaking Existing Batch Flow
**What goes wrong:** Interactive mode changes break the existing batch shipping pipeline.
**Why it happens:** Modifying shared code paths (CommandProcessor, intent parser) without sufficient guards.
**How to avoid:** Interactive mode is an ADDITIVE branch. The intent parser gets a new `is_interactive` flag. The CommandProcessor gets a new `_process_interactive()` method. Existing paths are untouched.
**Warning signs:** Existing tests failing after interactive mode changes.

### Pitfall 3: Forgetting UPS Required Fields
**What goes wrong:** Shipment creation fails because a required field is missing from the form.
**Why it happens:** UPS has specific required fields that are easy to miss.
**How to avoid:** The complete minimum required fields for UPS domestic shipment are documented below (see UPS Required Fields section). The schema generator MUST check all of them.
**Warning signs:** UPS API errors like "Missing required field" during shipment creation.

### Pitfall 4: Complex JSON Schema in Elicitation
**What goes wrong:** Frontend cannot render the form because the schema uses nested objects or arrays.
**Why it happens:** Developer adds object-type properties or arrays to the schema.
**How to avoid:** Per MCP elicitation spec, schemas MUST be flat objects with primitive properties only. Types allowed: string, number/integer, boolean, and enum (string with `oneOf` or `enum`). Multi-select uses `type: "array"` with `items: { anyOf: [...] }`.
**Warning signs:** Frontend form renderer encounters unknown schema types.

### Pitfall 5: No Data Source Connected = Blocked
**What goes wrong:** User cannot use interactive mode because the UI requires a data source.
**Why it happens:** The input is disabled when `hasDataSource` is false in CommandCenter.tsx.
**How to avoid:** Interactive mode must work WITHOUT a data source. Either: (a) allow command input when no source is connected but intent is interactive, or (b) add the "Interactive Ship" button that bypasses the data source requirement.
**Warning signs:** User sees "Connect a data source to begin..." when trying to use interactive mode.

### Pitfall 6: Phone Number and Address Normalization
**What goes wrong:** UPS rejects the shipment because phone has formatting characters or address is too long.
**Why it happens:** User enters raw data in the form without normalization.
**How to avoid:** The `build_ship_to()` function in `ups_payload_builder.py` already normalizes phones (`normalize_phone`), zips (`normalize_zip`), and addresses (`truncate_address`). Route ALL form data through `build_shipment_request()` which calls these.
**Warning signs:** UPS errors about invalid phone format or address length.

## Code Examples

### Backend: Interactive Shipping Service

```python
# src/services/interactive_shipping.py
"""Deterministic schema generator and service for interactive single-shipment creation."""

from typing import Any

# Minimum UPS required fields for domestic shipment
UPS_REQUIRED_FIELDS: dict[str, dict[str, Any]] = {
    "ship_to_name": {
        "type": "string",
        "title": "Recipient Name",
        "description": "Full name of the person receiving the package",
        "minLength": 1,
        "maxLength": 35,
    },
    "ship_to_address1": {
        "type": "string",
        "title": "Street Address",
        "description": "Street address line 1",
        "minLength": 1,
        "maxLength": 35,
    },
    "ship_to_city": {
        "type": "string",
        "title": "City",
        "minLength": 1,
        "maxLength": 30,
    },
    "ship_to_state": {
        "type": "string",
        "title": "State",
        "description": "Two-letter state code (e.g., NY, CA)",
        "minLength": 2,
        "maxLength": 2,
        "pattern": "^[A-Z]{2}$",
    },
    "ship_to_postal_code": {
        "type": "string",
        "title": "ZIP Code",
        "description": "5-digit or ZIP+4 format",
        "pattern": "^\\d{5}(-\\d{4})?$",
    },
    "weight": {
        "type": "number",
        "title": "Package Weight (lbs)",
        "description": "Weight in pounds",
        "minimum": 0.1,
        "maximum": 150,
    },
    "service_code": {
        "type": "string",
        "title": "Shipping Service",
        "oneOf": [
            {"const": "03", "title": "UPS Ground (3-5 business days)"},
            {"const": "02", "title": "2nd Day Air (2 business days)"},
            {"const": "01", "title": "Next Day Air (1 business day)"},
            {"const": "12", "title": "3 Day Select (3 business days)"},
            {"const": "13", "title": "Next Day Air Saver"},
        ],
        "default": "03",
    },
}

# Fields with sensible defaults (not required in form)
UPS_DEFAULT_FIELDS: dict[str, Any] = {
    "ship_to_country": "US",
    "packaging_type": "02",  # Customer Supplied Package
}

# Optional fields user may provide
UPS_OPTIONAL_FIELDS: dict[str, dict[str, Any]] = {
    "ship_to_address2": {
        "type": "string",
        "title": "Address Line 2",
        "description": "Apt, Suite, Unit, etc.",
        "maxLength": 35,
    },
    "ship_to_phone": {
        "type": "string",
        "title": "Phone Number",
        "description": "10-digit phone number",
    },
    "ship_to_company": {
        "type": "string",
        "title": "Company Name",
        "maxLength": 35,
    },
    "length": {
        "type": "number",
        "title": "Length (inches)",
        "minimum": 1,
    },
    "width": {
        "type": "number",
        "title": "Width (inches)",
        "minimum": 1,
    },
    "height": {
        "type": "number",
        "title": "Height (inches)",
        "minimum": 1,
    },
}


def generate_shipping_form_schema(
    initial_data: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Generate MCP-compliant flat JSON Schema for missing shipping fields.

    Args:
        initial_data: Fields already extracted from NL command.

    Returns:
        Tuple of (json_schema, message_string).
        Schema is flat with primitive types only per MCP elicitation spec.
    """
    properties: dict[str, Any] = {}
    required: list[str] = []
    pre_filled_count = 0

    for field_name, field_schema in UPS_REQUIRED_FIELDS.items():
        schema_copy = dict(field_schema)
        if field_name in initial_data and initial_data[field_name]:
            # Pre-fill with extracted value as default
            schema_copy["default"] = initial_data[field_name]
            pre_filled_count += 1
        required.append(field_name)
        properties[field_name] = schema_copy

    # Include optional fields without defaults
    for field_name, field_schema in UPS_OPTIONAL_FIELDS.items():
        schema_copy = dict(field_schema)
        if field_name in initial_data and initial_data[field_name]:
            schema_copy["default"] = initial_data[field_name]
        properties[field_name] = schema_copy

    missing_count = len(UPS_REQUIRED_FIELDS) - pre_filled_count
    if missing_count == 0:
        message = "All required fields found. Please confirm the details below:"
    else:
        message = f"Found {pre_filled_count} of {len(UPS_REQUIRED_FIELDS)} required fields. Please fill in the remaining details:"

    schema = {
        "type": "object",
        "properties": properties,
        "required": required,
    }

    return schema, message
```

### Backend: Updated Intent Model

```python
# Additions to src/orchestrator/models/intent.py
class ShippingIntent(BaseModel):
    # ... existing fields ...
    is_interactive: bool = Field(
        default=False,
        description="True when command is a direct ship-to instruction without data source",
    )
    initial_data: dict | None = Field(
        default=None,
        description="Partial shipment data extracted from NL command for interactive mode",
    )
```

### Backend: API Schema for Interactive Flow

```python
# Additions to src/api/schemas.py
class InteractiveShipmentRequest(BaseModel):
    """Request schema for submitting interactive shipment form data."""
    form_data: dict = Field(..., description="User-filled form data matching the schema")
    job_id: str | None = Field(None, description="Existing job ID if resuming")

class ElicitationResponse(BaseModel):
    """Response when elicitation is needed."""
    action: Literal["elicit"] = "elicit"
    message: str
    schema: dict = Field(..., description="MCP-compliant flat JSON Schema")
    initial_data: dict = Field(default_factory=dict, description="Pre-filled values from NL command")
    job_id: str | None = None
```

### Frontend: DynamicFormRenderer Component

```tsx
// frontend/src/components/DynamicFormRenderer.tsx
import * as React from 'react';

interface SchemaProperty {
  type: string;
  title?: string;
  description?: string;
  default?: string | number | boolean;
  minimum?: number;
  maximum?: number;
  minLength?: number;
  maxLength?: number;
  pattern?: string;
  format?: string;
  enum?: string[];
  oneOf?: Array<{ const: string; title: string }>;
}

interface FormSchema {
  type: "object";
  properties: Record<string, SchemaProperty>;
  required?: string[];
}

interface DynamicFormRendererProps {
  schema: FormSchema;
  message: string;
  initialData?: Record<string, unknown>;
  onSubmit: (data: Record<string, unknown>) => void;
  onCancel: () => void;
  isSubmitting?: boolean;
}

export function DynamicFormRenderer({
  schema,
  message,
  initialData,
  onSubmit,
  onCancel,
  isSubmitting,
}: DynamicFormRendererProps) {
  const [formData, setFormData] = React.useState<Record<string, unknown>>(() => {
    // Initialize from defaults in schema + initialData
    const defaults: Record<string, unknown> = {};
    for (const [key, prop] of Object.entries(schema.properties)) {
      if (initialData?.[key] !== undefined) {
        defaults[key] = initialData[key];
      } else if (prop.default !== undefined) {
        defaults[key] = prop.default;
      }
    }
    return defaults;
  });

  const required = new Set(schema.required || []);

  const renderField = (key: string, prop: SchemaProperty) => {
    const isRequired = required.has(key);
    const value = formData[key] ?? '';

    // Enum with oneOf -> Select/dropdown
    if (prop.oneOf) {
      return (
        <select
          value={String(value)}
          onChange={(e) => setFormData((prev) => ({ ...prev, [key]: e.target.value }))}
          className="w-full px-3 py-2 bg-slate-800/70 border border-slate-700 rounded-md text-sm text-slate-200"
        >
          <option value="">Select...</option>
          {prop.oneOf.map((opt) => (
            <option key={opt.const} value={opt.const}>{opt.title}</option>
          ))}
        </select>
      );
    }

    // Enum without oneOf -> Select
    if (prop.enum) {
      return (
        <select
          value={String(value)}
          onChange={(e) => setFormData((prev) => ({ ...prev, [key]: e.target.value }))}
          className="w-full px-3 py-2 bg-slate-800/70 border border-slate-700 rounded-md text-sm text-slate-200"
        >
          <option value="">Select...</option>
          {prop.enum.map((opt) => (
            <option key={opt} value={opt}>{opt}</option>
          ))}
        </select>
      );
    }

    // Number/integer -> number input
    if (prop.type === 'number' || prop.type === 'integer') {
      return (
        <input
          type="number"
          value={value === '' ? '' : Number(value)}
          onChange={(e) => setFormData((prev) => ({
            ...prev,
            [key]: e.target.value ? Number(e.target.value) : '',
          }))}
          min={prop.minimum}
          max={prop.maximum}
          step={prop.type === 'integer' ? 1 : 0.1}
          required={isRequired}
          className="w-full px-3 py-2 bg-slate-800/70 border border-slate-700 rounded-md text-sm text-slate-200"
        />
      );
    }

    // Boolean -> checkbox
    if (prop.type === 'boolean') {
      return (
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={!!value}
            onChange={(e) => setFormData((prev) => ({ ...prev, [key]: e.target.checked }))}
          />
          <span className="text-sm text-slate-300">{prop.title}</span>
        </label>
      );
    }

    // Default: string -> text input
    return (
      <input
        type={prop.format === 'email' ? 'email' : 'text'}
        value={String(value)}
        onChange={(e) => setFormData((prev) => ({ ...prev, [key]: e.target.value }))}
        minLength={prop.minLength}
        maxLength={prop.maxLength}
        pattern={prop.pattern}
        required={isRequired}
        placeholder={prop.description || ''}
        className="w-full px-3 py-2 bg-slate-800/70 border border-slate-700 rounded-md text-sm text-slate-200 placeholder:text-slate-500"
      />
    );
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit(formData);
  };

  return (
    <div className="card-premium p-4 space-y-4 animate-scale-in border-gradient">
      <h3 className="text-sm font-medium text-slate-200">Interactive Shipment</h3>
      <p className="text-xs text-slate-400">{message}</p>

      <form onSubmit={handleSubmit} className="space-y-3">
        {Object.entries(schema.properties).map(([key, prop]) => (
          <div key={key}>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              {prop.title || key}
              {required.has(key) && <span className="text-red-400 ml-1">*</span>}
            </label>
            {renderField(key, prop)}
          </div>
        ))}

        <div className="flex gap-3 pt-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={isSubmitting}
            className="flex-1 btn-secondary py-2.5"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={isSubmitting}
            className="flex-1 btn-primary py-2.5"
          >
            {isSubmitting ? 'Creating Shipment...' : 'Create Shipment'}
          </button>
        </div>
      </form>
    </div>
  );
}
```

### Frontend: "Interactive Ship" Button

```tsx
// Added to CommandCenter.tsx welcome message or input area
<button
  onClick={() => {
    // Start interactive flow without a NL command
    // Sends a special request that returns the full form schema
    startInteractiveShipment();
  }}
  className="btn-secondary py-2 px-4 flex items-center gap-2"
>
  <PackageIcon className="w-4 h-4" />
  <span>Interactive Ship</span>
</button>
```

## UPS Required Fields (Verified from Codebase)

These are the exact fields required for UPS domestic shipment creation, verified from `build_shipment_request()`, `build_ship_to()`, and `build_ups_api_payload()` in `src/services/ups_payload_builder.py`:

### Minimum Required (ShipTo)
| Field | UPS API Key | Source | Notes |
|-------|-------------|--------|-------|
| Recipient Name | `ShipTo.Name` | `ship_to_name` | Max 35 chars, truncated by `truncate_address()` |
| Address Line 1 | `ShipTo.Address.AddressLine[0]` | `ship_to_address1` | Max 35 chars |
| City | `ShipTo.Address.City` | `ship_to_city` | Required |
| State | `ShipTo.Address.StateProvinceCode` | `ship_to_state` | 2-letter code |
| ZIP Code | `ShipTo.Address.PostalCode` | `ship_to_postal_code` | Normalized by `normalize_zip()` |
| Country | `ShipTo.Address.CountryCode` | `ship_to_country` | Default: "US" |

### Minimum Required (Package)
| Field | UPS API Key | Source | Notes |
|-------|-------------|--------|-------|
| Weight | `Package.PackageWeight.Weight` | `weight` | In LBS, min 0.1, max 150. Default 1.0 |
| Packaging Type | `Package.Packaging.Code` | `packaging_type` | Default: "02" (Customer Supplied) |

### Minimum Required (Service)
| Field | UPS API Key | Source | Notes |
|-------|-------------|--------|-------|
| Service Code | `Service.Code` | `service_code` | Default: "03" (Ground) |

### Provided Automatically (Shipper)
| Field | Source | Notes |
|-------|--------|-------|
| Shipper Name | `SHIPPER_NAME` env var | From `build_shipper_from_env()` |
| Shipper Address | `SHIPPER_ADDRESS1`, `SHIPPER_CITY`, etc. | From env vars |
| Account Number | `UPS_ACCOUNT_NUMBER` env var | For billing |

### Optional (Enhance Quality)
| Field | UPS API Key | Source | Notes |
|-------|-------------|--------|-------|
| Address Line 2 | `ShipTo.Address.AddressLine[1]` | `ship_to_address2` | Apt, Suite, etc. |
| Phone | `ShipTo.Phone.Number` | `ship_to_phone` | Normalized to digits only |
| Company | `ShipTo.AttentionName` | `ship_to_company` | Max 35 chars |
| Dimensions | `Package.Dimensions` | `length`, `width`, `height` | All three required if any |

## Current Elicitation System Analysis

### What Exists (Must Change)
The current elicitation system in `src/orchestrator/models/elicitation.py` uses proprietary `ElicitationQuestion` / `ElicitationOption` / `ElicitationResponse` models. These are NOT MCP-compliant.

**Current model:**
```python
class ElicitationQuestion:
    id: str
    header: str
    question: str
    options: list[ElicitationOption]  # NOT MCP spec
    allow_free_text: bool
    multi_select: bool
    required: bool
```

**MCP spec requires:**
```json
{
  "type": "object",
  "properties": {
    "field_name": {
      "type": "string|number|boolean",
      "title": "Display Name",
      "description": "Help text",
      "default": "pre-filled value"
    }
  },
  "required": ["field_name"]
}
```

### What Needs to Change
1. **Backend elicitation response format**: Return flat JSON Schema instead of `ElicitationQuestion` objects
2. **Frontend form rendering**: New `DynamicFormRenderer` component that reads JSON Schema and generates inputs
3. **Response format**: Return `{action: "accept"|"decline"|"cancel", content: {...}}` per MCP spec
4. **Existing elicitation templates** in `elicitation.py` can remain for batch-mode clarification questions, but the interactive shipping path uses the new JSON Schema format

### Migration Strategy
- Do NOT remove existing `ElicitationQuestion` model yet (batch mode still uses it)
- Add new JSON Schema-based elicitation path for interactive shipping
- Frontend `ConversationMessage` metadata already has `action: 'elicit'` -- use this to trigger form rendering
- The `metadata.elicitation` field in `useAppState.tsx` currently has `questions: Array<{id, question, options}>` -- extend to support `schema: object` for JSON Schema mode

## CommandCenter Message Flow Analysis

The `CommandCenter.tsx` currently handles these message actions via `ConversationMessage.metadata.action`:

| Action | Behavior | Component |
|--------|----------|-----------|
| `'preview'` | Shows PreviewCard with shipment samples | PreviewCard |
| `'execute'` | Shows ProgressDisplay with SSE | ProgressDisplay |
| `'complete'` | Shows CompletionArtifact card | CompletionArtifact |
| `'error'` | Shows error in SystemMessage | SystemMessage |
| `'elicit'` | Currently defined in types but NOT rendered | **TODO: DynamicFormRenderer** |

The `'elicit'` action already exists in the `ConversationMessage` metadata type definition but has no renderer. This is the integration point for the dynamic form.

### Data Flow for Interactive Shipping

```
1. User types "Ship 5lb box to John Smith, 123 Main St, NY 10001"
   OR clicks "Interactive Ship" button

2. Frontend: POST /api/v1/commands  (or POST /api/v1/interactive/start)
   → Backend: parse_intent() detects is_interactive=True
   → Backend: Extracts initial_data = {ship_to_name: "John Smith", weight: 5.0, ...}
   → Backend: generate_shipping_form_schema(initial_data)
   → Returns: {action: "elicit", schema: {...}, initial_data: {...}, message: "..."}

3. Frontend: CommandCenter receives elicit response
   → Adds system message with metadata.action = 'elicit'
   → Renders DynamicFormRenderer inline in chat
   → Form pre-fills extracted fields, shows empty fields for missing data

4. User fills form and clicks "Create Shipment"
   → Frontend: POST /api/v1/interactive/submit {form_data: {...}}
   → Backend: Creates Job + single JobRow from form_data
   → Backend: build_shipment_request(order_data, shipper)
   → Backend: BatchEngine.preview() for rate quote
   → Returns preview (single row)

5. Frontend shows single-row PreviewCard (or auto-confirms for interactive)
   → User confirms
   → Backend: BatchEngine.execute() with single row
   → UPS API call → tracking number + label
   → SSE progress → CompletionArtifact

6. User sees CompletionArtifact with "View Labels" button
   → Same flow as batch completion
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Proprietary ElicitationQuestion | MCP JSON Schema elicitation | MCP spec 2025-06-18 | Industry-standard form schema |
| LLM-generated forms | Deterministic schema generation | Best practice | <500 tokens, deterministic |
| Separate single-shipment API | Single-row Job through BatchEngine | This phase | Code reuse, consistent audit trail |

**Deprecated/outdated:**
- `ElicitationQuestion`/`ElicitationOption` proprietary models: Should be superseded by JSON Schema for interactive mode (keep for batch clarification until migrated)

## Open Questions

1. **Preview step for interactive mode**
   - What we know: Batch mode always shows preview before execution
   - What's unclear: Should interactive mode also show a preview, or go straight to execution after form submission?
   - Recommendation: Show a compact single-row preview with rate quote and Confirm/Cancel. Reuses existing PreviewCard. User expects to see cost before committing.

2. **Input enablement without data source**
   - What we know: Currently `CommandCenter` disables input when `hasDataSource === false`
   - What's unclear: How to enable input for interactive mode while still blocking batch mode without a source
   - Recommendation: Allow input when no data source is connected. If the intent parser detects a batch command (references a file/Shopify), show error "Connect a data source first." If it detects interactive command, proceed. The "Interactive Ship" button bypasses this entirely.

3. **Address validation before shipment**
   - What we know: UPS has `validate_address` tool available
   - What's unclear: Should interactive mode auto-validate the address before creating the shipment?
   - Recommendation: Defer to v2. For MVP, let UPS shipment creation handle address issues (it returns errors for invalid addresses). Address validation can be an optional enhancement.

4. **Handling elicitation for batch mode vs interactive mode**
   - What we know: Batch mode uses `ElicitationQuestion`, interactive uses JSON Schema
   - What's unclear: Should we migrate batch elicitation to JSON Schema too?
   - Recommendation: Keep both for now. Batch elicitation works and is tested. Phase 8 adds JSON Schema for interactive only. Migration can happen in a future phase.

## Sources

### Primary (HIGH confidence)
- **Codebase files read directly**: `src/orchestrator/models/intent.py`, `src/orchestrator/nl_engine/intent_parser.py`, `src/orchestrator/nl_engine/elicitation.py`, `src/orchestrator/nl_engine/engine.py`, `src/orchestrator/models/elicitation.py`, `src/services/command_processor.py`, `src/services/ups_payload_builder.py`, `src/services/batch_engine.py`, `src/services/ups_service.py`, `src/api/routes/commands.py`, `src/api/schemas.py`, `src/db/models.py`, `frontend/src/components/CommandCenter.tsx`, `frontend/src/hooks/useAppState.tsx`, `frontend/src/types/api.ts`, `frontend/src/lib/api.ts`
- [MCP Elicitation Specification (2025-11-25)](https://modelcontextprotocol.io/specification/2025-11-25/client/elicitation) - Full elicitation spec with form mode JSON Schema restrictions, response actions (accept/decline/cancel), and primitive type constraints
- [MCP Schema TypeScript definitions](https://github.com/modelcontextprotocol/specification/blob/main/schema/2025-11-25/schema.ts) - `ElicitRequestFormParams`, `ElicitResult`, `PrimitiveSchemaDefinition` types

### Secondary (MEDIUM confidence)
- [MCP Spec Anniversary Blog](http://blog.modelcontextprotocol.io/posts/2025-11-25-first-mcp-anniversary/) - Context on elicitation feature introduction
- [MCP Spec Updates Blog](https://forgecode.dev/blog/mcp-spec-updates/) - Overview of 2025-06-18 changes including elicitation

### Tertiary (LOW confidence)
- [@rjsf/shadcn npm package](https://www.npmjs.com/package/@rjsf/shadcn) - Evaluated but not recommended; adds unnecessary dependency for flat schema forms

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All libraries already in project, no new deps needed
- Architecture: HIGH - Based on direct codebase analysis, clear integration points identified
- UPS Required Fields: HIGH - Verified from actual `ups_payload_builder.py` source code
- MCP Elicitation Spec: HIGH - Read directly from official specification
- Pitfalls: HIGH - Based on analysis of existing codebase patterns and UPS API lessons in CLAUDE.md
- Frontend patterns: HIGH - Based on direct reading of CommandCenter.tsx and useAppState.tsx

**Research date:** 2026-02-12
**Valid until:** 60 days (stable domain, no fast-moving dependencies)
