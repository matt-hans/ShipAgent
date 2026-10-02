# Origin-based visibility in registry contracts

**Purpose:** records how public registry contracts and validators implement
[ADR 0007](../adr/0007-origin-based-provider-redaction.md) (accepted; not
amended). Issue #47 chose to preserve the ADR rather than move to opaque-only
contracts.

## Contract fields (`ToolContract`)

| Field | Meaning | Constraint |
| --- | --- | --- |
| `provider_originated_fields` | Output paths that may echo text the user supplied in the provider conversation (for example `address_text`). | Requires `result_profile="provider_ingress_echo"`. Lifts only the customer-address check. |
| `signed_download_fields` | Output paths that may carry a short-lived signed label download URL. | Requires `result_profile="artifact_action"`, a bounded `^https://` string, and a sibling `expires_in_seconds` integer with `maximum <= 300`. Lifts only the label/document URL check. |

Never lifted for any field: credentials/tokens, raw carrier request/response,
row arrays, and label bytes/base64/content. Undeclared fields stay fail-closed.

Canonical modules: `src/registry/privacy.py` (validators, `DataOrigin`, sensitive
key sets), `src/registry/vocabulary.py` (status capability vocabulary),
`src/control_plane/result_projection.py` (runtime gate).

## Runtime gate

`project_result(contract, result, field_origins=...)` fails closed when a
declared echo field is present without `DataOrigin.provider_supplied` metadata,
and rejects signed URLs that are not plain `https` (no userinfo, no fragment).
Error messages never include the offending value.

## Implementation obligations (not implemented here)

The affected tools (`validate_shipment_address`, `create_label_download`) remain
`provider_export_enabled=False`; only `get_shipagent_status` is exported. Before
enabling either, an implementation must:

1. Tag each echo field with its true origin from the Shipment Source; imported
   or active-source data must omit `address_text` entirely.
2. Mint the signed URL on the Execution Target flow: single-use, TTL
   <= 300 s, bound to an Auth0 browser session of the same Cloud Account;
   possession alone is not authorization.
3. Stream label bytes desktop-to-browser with no cloud persistence.
4. Keep the #46 confirmation/grant gates and non-status export disablement
   intact, and add tests with synthetic canaries at those seams.

Rollback: revert the PR; the new `ToolContract` fields default to empty and no
exported provider artifact changed.
