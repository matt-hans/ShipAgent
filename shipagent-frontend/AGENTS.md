# ShipAgent Frontend Agent Guide

## Scope

This file applies to `shipagent-frontend/`. It augments the repo-wide
instructions in `../AGENTS.md`.

## Frontend Shape

ShipAgent's active frontend is an Angular 21 + Nx 22 workspace using Native
Federation.

- `apps/shell/` is the host application. It owns the page frame, remote loading,
  root providers, API base URL setup, and Tauri-aware bootstrap.
- `apps/chat-remote/` owns conversation UI, SSE event handling, previews,
  progress, chat actions, token highlighting, and document upload flows.
- `apps/sidebar-remote/` owns data sources, job/session navigation, and adjacent
  sidebar workflows.
- `apps/settings-remote/` owns settings, provider credentials, connections,
  shipment behavior, and onboarding. Keep Anthropic/OpenAI/Gemini model
  settings aligned with backend `AGENT_MODEL` and provider connection contracts.
- `apps/domain-remote/` owns domain cards and card registry behavior.
- `apps/provider-widget/` is a provider/app-store widget surface.
- `libs/shared/api/`, `libs/shared/types/`, `libs/shared/state/`,
  `libs/shared/sse/`, `libs/shared/tauri/`, and `libs/testing/` are the shared
  contracts and utilities. Prefer extending these over duplicating code inside
  individual remotes.

## Working Rules

- Use npm and `package-lock.json`. Do not introduce pnpm/yarn lockfiles.
- Run tasks through Nx with `npx nx ...`; do not rely on a global Nx install.
- Keep Native Federation boundaries explicit. The shell loads remotes through
  `RemoteLoaderService`; remotes expose standalone components/services through
  their federation config and remote entry files.
- Put backend DTO changes in `libs/shared/types/src/` and API calls in
  `libs/shared/api/src/`. Keep app components focused on presentation and local
  orchestration.
- Use NgRx SignalStores in `libs/shared/state/src/` for shared state. Avoid
  parallel ad hoc services for the same cross-remote state.
- Use `libs/shared/sse/src/` for EventSource/SSE behavior. Do not implement
  competing stream parsers in remotes.
- Use `libs/shared/tauri/src/` for sidecar detection and API port resolution.
  Browser dev should continue to use `/api/v1`; Tauri should use the resolved
  `127.0.0.1` sidecar URL.
- Preserve the mandatory preview/confirmation UX for shipments, pickups, and any
  state-changing shipping action.
- Keep provider selection UI provider-neutral. The frontend may collect and show
  provider credentials/settings, but shipping behavior and tool routing remain
  backend workflow concerns.
- Do not render raw labels, document bytes, row samples, credentials, or raw UPS
  request/response bodies from conversation tool payloads. Use backend-sanitized
  artifacts and event payloads.
- Prefer accessible, dense operational UI. This is a shipping workflow tool, not
  a marketing site.

## Commands

Install:

```bash
npm ci
```

Serve the shell in dev:

```bash
npx nx serve shell
```

Targeted validation:

```bash
npx nx typecheck <project>
npx nx lint <project>
npx nx test <project>
npx nx build <project> --configuration=production
```

Broad validation:

```bash
npx nx run-many -t typecheck --all
npx nx run-many -t lint --all
npx nx run-many -t test --all
npx nx run-many -t build --all --configuration=production
./scripts/link-remotes.sh
```

Use `npx nx affected -t typecheck lint test` when a change is limited and Nx can
compute the affected graph.

## Integration Notes

- Backend routes are rooted at `/api/v1`; `ApiService` centralizes HTTP access.
- Conversation streaming is SSE-based. `ApiService` returns stream URLs; stream
  consumption belongs in the SSE/conversation services.
- Provider-neutral conversation results can include sanitized tool payloads for
  rates, address validation, transit estimates, tracking, pickups, landed cost,
  contacts, and previews. UI components should treat backend event/data shapes as
  contracts and update shared fixtures when they change.
- Production serving expects the Angular shell build at
  `shipagent-frontend/dist/apps/shell/browser`, with remotes linked into the
  shell dist after production builds.
- If a component changes a shared type, event shape, or API contract, update the
  corresponding backend schema/test or add a frontend fixture in `libs/testing/`.

<!-- nx configuration start-->
<!-- Leave the start & end comments to automatically receive updates. -->

# General Guidelines for working with Nx

- For navigating/exploring the workspace, invoke the `nx-workspace` skill first - it has patterns for querying projects, targets, and dependencies
- When running tasks (for example build, lint, test, e2e, etc.), always prefer running the task through `nx` (i.e. `nx run`, `nx run-many`, `nx affected`) instead of using the underlying tooling directly
- Prefix nx commands with the workspace's package manager (e.g., `pnpm nx build`, `npm exec nx test`) - avoids using globally installed CLI
- You have access to the Nx MCP server and its tools, use them to help the user
- For Nx plugin best practices, check `node_modules/@nx/<plugin>/PLUGIN.md`. Not all plugins have this file - proceed without it if unavailable.
- NEVER guess CLI flags - always check nx_docs or `--help` first when unsure

## Scaffolding & Generators

- For scaffolding tasks (creating apps, libs, project structure, setup), ALWAYS invoke the `nx-generate` skill FIRST before exploring or calling MCP tools

## When to use nx_docs

- USE for: advanced config options, unfamiliar flags, migration guides, plugin configuration, edge cases
- DON'T USE for: basic generator syntax (`nx g @nx/react:app`), standard commands, things you already know
- The `nx-generate` skill handles generator discovery internally - don't call nx_docs just to look up generator syntax

<!-- nx configuration end-->
