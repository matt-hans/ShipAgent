# UPS MCP Hosted Contract

ShipAgent hosted marketplace runtime depends on an external UPS MCP server. That
server lives in a separate repository. This document defines the contract
ShipAgent validates before using that server in hosted production. The UPS MCP
server is a private carrier integration boundary, not a model-planning layer or
public marketplace app surface.

## Required Tools

The UPS MCP server must expose these MCP tools for hosted-v1:

- `rate_shipment`
- `validate_address`
- `create_shipment`
- `shipagent_capabilities`

`shipagent_capabilities` is read-only and returns metadata. It must not call UPS.

The existing UPS MCP server may keep raw UPS API payloads as the default response
format for local development and existing users. ShipAgent hosted production
requires an explicit hosted-normalized response mode. Recommended tool
parameters:

- `rate_shipment(..., response_format="raw")`
- `validate_address(..., response_format="raw")`
- `create_shipment(..., response_format="raw", idempotency_key="")`

When `response_format="shipagent_v1"`, the required tools return the normalized
shapes below. `create_shipment` must require a non-empty deterministic
`idempotency_key` when `response_format="shipagent_v1"`. When omitted,
`response_format` defaults to `"raw"` and existing raw UPS response behavior
remains unchanged.

`raw` is compatibility guidance for the external UPS MCP server. ShipAgent
hosted readiness validates only that `shipagent_v1` is declared and supported;
`raw` is not a hosted readiness requirement.

## Capability Declaration

`shipagent_capabilities` returns:

```json
{
  "contract_version": "hosted-v1",
  "server_version": "1.2.3",
  "capabilities": [
    "rate_quote",
    "rate_shop",
    "address_validation",
    "create_shipment",
    "idempotency_metadata_passthrough",
    "shipment_response_normalization",
    "international_charges",
    "safe_error_mapping",
    "mutating_retry_policy"
  ],
  "response_formats": ["raw", "shipagent_v1"]
}
```

ShipAgent can infer `rate_quote`, `rate_shop`, `address_validation`, and
`create_shipment` from tool presence, but hosted production still requires the
declaration because the remaining guarantees are behavioral. ShipAgent also
requires `shipagent_v1` in `response_formats` because hosted normalized mode is
explicit and cannot be proven from capability names alone.

`contract_version` must be explicitly declared as `"hosted-v1"` for this
release. Missing, non-string, or different contract versions fail ShipAgent
hosted readiness closed.

`idempotency_metadata_passthrough` means the UPS MCP server accepts a
deterministic `idempotency_key`, preserves it in available UPS
transaction/correlation metadata, and returns it in the normalized response. It
does not claim the UPS API provides true idempotent create semantics. If true
carrier-level idempotent shipment creation is proven, the server may additionally
declare `carrier_idempotent_create`. This boundary phase validates only that the
normalized response echoes a non-empty `idempotencyKey`; later hosted
worker/execution code validates the exact
`hosted_job_id:preview_row_id:row_checksum` format and row-state match.

`international_charges` means the UPS MCP server can return normalized
international charge/customs-related shapes. It does not enable all
international lanes for ShipAgent hosted production. ShipAgent enables only
explicitly reviewed origin/destination lane fixtures in later hosted workflow
phases, and hosted readiness fails closed for any unreviewed lane.

`mutating_retry_policy` means the UPS MCP server does not generically replay a
mutating UPS operation after the carrier boundary may have been crossed. Only
pre-boundary or proven-not-processed failures may be retried by the UPS MCP
server under its own policy. ShipAgent's boundary validates the capability
declaration; the external UPS MCP server owns the UPS-specific retry proof and
execution behavior.

## Behavioral Guarantees

- `rate_shipment` supports UPS `requestoption="Rate"` for default purchasable previews.
- `rate_shipment` supports UPS `requestoption="Shop"` for explicit rate comparison.
- `validate_address` returns normalized statuses in `response_format="shipagent_v1"`: `valid`, `corrected`, `ambiguous`, `invalid`, `unsupported`, or `unknown`.
- `create_shipment` is mutating and must not be retried by generic MCP retry loops after the UPS boundary is crossed.
- `create_shipment` requires a deterministic `idempotency_key` from ShipAgent hosted workers when `response_format="shipagent_v1"` and preserves it through UPS transaction/correlation metadata where the UPS API supports it.
- Shipment responses are normalized before returning to ShipAgent when `response_format="shipagent_v1"` is requested.
- International shipping is supported only for configured, review-tested lanes in ShipAgent hosted production. Capability declaration alone never enables a hosted international lane.
- Domain failures in `response_format="shipagent_v1"` are returned as hosted-safe error envelopes. Raw UPS XML/JSON responses, exception traces, local paths, credentials, request payloads, and raw `details` must not cross this boundary.

## Normalized Response Requirements

Success response validators are minimum-shape validators. They allow additional
normalized metadata such as service descriptions, negotiated-rate flags,
warnings, transit estimates, correction notes, or charge breakdowns. Later
public result DTOs must still strip any hosted-unsafe fields before
transcript/widget output.

In `response_format="shipagent_v1"`, rate quote responses must include:

- `success: true`
- non-empty string `totalCharges.monetaryValue`
- non-empty string `totalCharges.currencyCode`

In `response_format="shipagent_v1"`, rate shop responses must include:

- `success: true`
- non-empty `ratedShipments`
- each option has non-empty string `serviceCode`
- each option has non-empty string `totalCharges.monetaryValue`
- each option has non-empty string `totalCharges.currencyCode`

In `response_format="shipagent_v1"`, address validation responses must include:

- `status`
- optional `candidates` array with normalized candidate data

In `response_format="shipagent_v1"`, shipment creation responses must include:

- `success: true`
- non-empty `idempotencyKey`
- non-empty string `shipmentIdentificationNumber`
- non-empty `trackingNumbers`
- each tracking number is a non-empty string
- non-empty string `totalCharges.monetaryValue`
- non-empty string `totalCharges.currencyCode`
- non-empty `labelData`
- each label has non-empty string `format`
- each label has `encoding: "base64"`
- each label has non-empty string `contentBase64`

The boundary validator treats `idempotencyKey` as shape-only: it must be a
non-empty string. It must not validate the hosted key format because this
package does not own hosted job IDs, preview row IDs, row checksums, or execution
state.

`contentBase64` is internal carrier-boundary data for ShipAgent hosted workers
only. ShipAgent persists it to tenant-scoped object storage and strips it before
any public MCP `structuredContent`, widget payload, job status, label link, or
audit summary response.

This boundary phase validates only the label response shape:

- `labelData` is non-empty
- each label has non-empty string `format`
- each label has `encoding: "base64"`
- each label has non-empty string `contentBase64`

Hosted worker/artifact phases own byte-level artifact safety:

- base64 decoding
- size limits
- content type sniffing
- label PDF/image validation
- malware scanning
- tenant-scoped object storage
- signed-link publication

In `response_format="shipagent_v1"`, domain failure responses must include
exactly these top-level keys:

- `success: false`
- `error`

The nested `error` envelope must include exactly these keys:

- `error.code`
- `error.category`
- `error.message`
- `error.retryable`
- `error.correlation_id`

Allowed error categories are:

- `auth`
- `rate_limit`
- `validation`
- `service_unavailable`
- `address`
- `customs`
- `transport`
- `unknown`

The error envelope must contain only the top-level and nested keys listed above.
It must not include raw `details`, `raw`, `raw_response`, `request`,
`request_body`, `payload`, `stack`, `stack_trace`, `traceback`, `local_path`,
`path`, `credentials`, `secrets`, `client_secret`, or `access_token` keys at any
nesting level. Unlike success responses, safe-error envelopes are closed because
they are public-safety sensitive.

## ShipAgent Ownership

ShipAgent owns:

- tenant authorization
- connected account selection
- origin profile selection
- order batch persistence
- preview checksums
- approval records
- confirmation tokens
- shipment worker idempotency keys
- hosted label metadata
- transcript-safe result envelopes
- provider artifacts and widgets

For this boundary phase, ShipAgent implements only
`HostedUpsBoundaryAdapter.inspect_capabilities()`, the `UpsBoundaryClient`
protocol, hosted-v1 validators, hosted-v1 fixtures, and the readiness evaluator.
Later hosted worker phases own operation methods that call UPS MCP tools with
`response_format="shipagent_v1"`, validate success or safe-error envelopes before
consuming results, persist label artifacts, and strip internal
`labelData.contentBase64` before any public result.

The hosted worker path is deterministic ShipAgent code, not a second internal
LLM. User-facing model providers call public ShipAgent workflow tools; ShipAgent
then validates persisted server-side state and calls internal adapters.

The UPS MCP server owns:

- UPS API request execution
- UPS response normalization
- UPS-specific error normalization
- UPS API version compatibility
- UPS lane/service capability implementation

## Local Runtime

Desktop/local ShipAgent flows may continue using the Angular/Tauri shell,
FastAPI sidecar, local conversation runtime, local model-provider configuration,
environment fallback, and local credential resolution. Hosted marketplace
readiness must use this contract and fail closed when the external UPS MCP
server does not satisfy it. `degraded` readiness is diagnostic only; hosted
production startup must require `status == "ready"` and fail closed for both
`not_ready` and `degraded`.
