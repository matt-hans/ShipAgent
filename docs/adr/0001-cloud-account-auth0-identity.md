# ADR 0001: ShipAgent Cloud Account And Auth0 Identity

## Status

Accepted

## Decision

Auth0 authenticates humans and issues OAuth grants. ShipAgent owns an opaque
Cloud Account ID mapped one-to-one to the stable Auth0 `sub`. Provider clients are
independently revocable Provider Connections and never define account identity.

Grant timing is provider-specific. ChatGPT may begin with read/status scopes and
reauthorize incrementally for preview or execution. Claude custom connectors
request the full MVP scope set when connected because portable incremental
per-tool escalation is not guaranteed. Messages API clients supply their own
appropriately scoped Auth0 token. OAuth scope alone never authorizes a shipment
purchase; explicit ShipAgent approval and a one-time Execution Grant remain
mandatory.

Public provider tools use four stable Auth0 scopes:
`shipagent.status`, `shipagent.preview`, `shipagent.execute`, and
`shipagent.artifacts`. Granular colon-delimited scopes are internal contracts and
are not exported to ChatGPT or Claude. Job status is reference-scoped
continuation rather than general account-history access.

Provider-callable Approval Requests, Execution Grants, job references, poll
references, and label-reference creation are isolated to the originating
Provider Connection. Another connection for the same Cloud Account cannot
continue or retrieve that workflow. Authenticated browser pages bind to the
Cloud Account while preserving the originating connection on the opaque
reference.

Claude custom connectors and Messages API applications are distinct provider
surfaces. Each authorized Messages API OAuth client ID creates its own
independently revocable Provider Connection; it does not share identity or
continuation references with claude.ai or another API client.

ShipAgent Desktop links independently to the Cloud Account through its own Auth0
Authorization Code + PKCE browser flow with a loopback callback. Its OAuth
client receives device-management scopes, not provider workflow scopes. The
resulting token is used to register the desktop public key and installation
identity; subsequent relay reconnects use device proof of possession rather
than retaining the Auth0 access token.

The loopback-only local sidecar receives the OAuth callback on an OS-assigned
`127.0.0.1` port. ShipAgent does not put OAuth codes or tokens in
`shipagent://` deep links.
