# Auth0 Provider Clients (Synthetic Qualification)

The hosted MCP resource uses Auth0-issued bearer tokens and independently
revocable Provider Connections. This document describes the code contract,
not a completed Auth0 setup or actual ChatGPT/Claude qualification.

## Exact resource and audience

Example configuration (illustrative placeholders, not provisioned resources):

```dotenv
SHIPAGENT_PUBLIC_BASE_URL=https://dev-mcp.shipagent.app
SHIPAGENT_AUTH0_AUDIENCE=https://dev-mcp.shipagent.app/mcp
SHIPAGENT_AUTH0_ISSUER=https://your-approved-tenant.example/
```

The public base may be the origin or its exact `/mcp` endpoint, optionally with a
trailing slash. Other paths, duplicated `/mcp`, user information, query strings,
fragments and non-loopback HTTP fail startup. Raw dot segments, backslashes and
control characters are rejected before URL normalization. Prefix/proxy deployments need a
separately tested routing contract. Request `Host` and forwarded headers do not
select the OAuth resource or issuer.

- Entered connector URL and canonical OAuth resource: `https://dev-mcp.shipagent.app/mcp`
- Protected-resource metadata: `https://dev-mcp.shipagent.app/.well-known/oauth-protected-resource/mcp`
- The root metadata alias returns the same document and exact `/mcp` resource.
- The HTTP mount may redirect `/mcp` to `/mcp/`; this does not add a second OAuth audience.
- Authorization and token requests must carry the exact canonical resource, and
  the access token must include that resource as its audience.

Migration from the old origin-only audience is deliberately fail closed.
Changing the deployment's registered API audience/client grants is a separate
operator-authorized Auth0 configuration task. The server does not accept the
old origin as an alternate audience, rewrite tokens or silently migrate grants.

## Transport and per-request authorization

The production HTTP facade is stateless: initialize, list and call work without
allocating an MCP transport session. A supplied `Mcp-Session-Id` conveys no
identity or continuation authority. Authenticated GET/SSE subscriptions and
DELETE/session operations return 405; unauthenticated requests still receive
401. Server-initiated notifications, transport replay and session subscriptions
are unsupported. Durable Agent Run References on the target provide workflow
continuity independently of transport sessions.

Every HTTP tool call reads the verified authorization on the current SDK
request, including current account, connection and scopes. An initialization
ContextVar or HTTP-request fallback cannot preserve stale authority. Tests also
exercise an explicitly stateful transport to guard that boundary independently
of the production setting, plus account suspension/connection revocation through
real local authorization persistence. This is not a claim of SDK session binding
or real-client qualification.

## Public permissions and trusted clients

The only advertised provider scopes are `shipagent.status`, `shipagent.preview`,
`shipagent.execute` and `shipagent.artifacts` (ADRs 0001/0009). Metadata describes
the public permission vocabulary; it does not enable dormant tools. The default
production export remains target status only. Preview can authorize charged
ShipAgent model work after its separate provisioning/usage gate. Execute always
requires the reviewed human approval and exact-target execution safeguards;
OAuth scope is never sufficient purchase authority.

Device/target management remains a separately authenticated operator or desktop
purpose. Provider tokens cannot manage targets even if they contain management
scopes. Management scopes and granular internal scopes are not advertised in
provider metadata. Existing operator purpose and recent-authentication checks
are unchanged.

`SHIPAGENT_AUTH0_PROVIDER_CLIENTS` maps trusted, explicitly approved client IDs to
surfaces. The example defaults (`chatgpt-client`, `claude-client`,
`desktop-client`, `operator-client`) are synthetic identifiers. An actual
client registration, CIMD identity or callback must be approved and verified
before it is trusted. Client names, model input, request headers, callback names
or arbitrary dynamic registrations cannot establish a trusted provider surface.
The desktop uses its separate Authorization Code + PKCE flow; headless enrollment
follows ADR 0009 and does not presume a Device Authorization grant.

## Offline checks and later client gates

```bash
.venv/bin/python scripts/check_provider_oauth_metadata.py https://dev-mcp.shipagent.app/mcp
.venv/bin/python -m pytest tests/control_plane/test_oauth_mcp_compatibility.py tests/control_plane/test_oauth_mcp_wire.py
```

The metadata checker validates shape/resource/scope agreement only. Synthetic
HTTP tests use disposable signed tokens, TestClient/ASGI requests plus a
loopback Uvicorn/httpx multi-request test, and fake external boundaries. They do not establish issuer discovery, PKCE/state,
registration, consent, refresh/revocation or actual-client compatibility.

Issue #78 stays open until separately authorized actual ChatGPT and Claude
custom-connector tests pass on the same source/configuration. Required setup
includes a bounded approved HTTPS endpoint, exact owner/destination, actual
client IDs/callbacks, issuer/token authentication methods, credential setup and
operating/model costs. Record source commit, client product/plan/version/date,
passed/failed/blocked cases, denied consent, expiry, reconnect, revocation and
cross-account/connection attempts. No production or directory-readiness claim
follows from local tests.

## Primary-source compatibility notes (checked 2026-10-08)

- [OpenAI Plugins authentication](https://developers.openai.com/plugins/build/auth)
  is the current destination of the older Apps SDK auth URL. It requires
  resource/audience agreement, per-tool OAuth schemes and structured tool-level
  authentication challenges. Copy the exact callback shown for the approved
  connection; do not assume a universal static callback or client ID.
- [MCP authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)
  and [discovery](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/authorization-server-discovery)
  define resource indicators and path-aware protected-resource discovery.
- [Claude custom connectors](https://support.anthropic.com/en/articles/11503834-building-custom-integrations-via-remote-mcp-servers)
  documents OAuth and Streamable HTTP support. Real client behavior still needs
  the above qualification. [Claude Messages API MCP](https://platform.claude.com/docs/en/agents-and-tools/mcp-connector)
  is a different surface: API consumers obtain and refresh their own bearer
  token; it is not evidence of the custom-connector login flow.
