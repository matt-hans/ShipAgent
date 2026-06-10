# Auth0 Provider Clients (Internal Prototype)

This page defines the fixed Auth0 client set for the internal ShipAgent MCP
resource prototype and their OAuth surface expectations.

## Fixed MCP Resource

- OAuth resource: `https://dev-mcp.shipagent.app`

## Client Settings

| Client | Auth Flow | Secret | Notes |
| --- | --- | --- | --- |
| ChatGPT | Authorization Code + PKCE | No (public) | Maps to `client_id: chatgpt-client` and Surface `chatgpt`. |
| Claude.ai | Authorization Code + PKCE | No (public) | Maps to `client_id: claude-client` and Surface `claude_ai`. |
| Desktop | Device Authorization Grant | No (public desktop app) | Maps to `client_id: desktop-client` and Surface `desktop`. |
| Operator | Authorization Code + PKCE (web app) with MFA | Yes (confidential) | Maps to `client_id: operator-client` and Surface `operator`. Uses separate runtime audience for desktop-independent operator workflows. |

## Environment Mapping

Set `SHIPAGENT_AUTH0_PROVIDER_CLIENTS` as:

```json
{"chatgpt-client":"chatgpt","claude-client":"claude_ai","desktop-client":"desktop","operator-client":"operator"}
```

and configure:

- `SHIPAGENT_AUTH0_ISSUER`
- `SHIPAGENT_AUTH0_AUDIENCE` (currently `https://dev-mcp.shipagent.app`)

## Validation

Use:

```bash
.venv/bin/python scripts/check_provider_oauth_metadata.py https://dev-mcp.shipagent.app
```

This only verifies the metadata shape and does not output tokens or credentials.
