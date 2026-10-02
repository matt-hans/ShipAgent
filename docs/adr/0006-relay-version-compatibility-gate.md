# ADR 0006: Relay Version Compatibility Gate

## Status

Accepted

## Decision

The relay heartbeat reports core, registry-contract, and UPS-boundary versions
plus a capability list. Before dispatching any tool invocation, the control
plane checks these against a compatibility matrix derived from each
`ToolContract.minimum_capabilities`. Incompatible targets receive no
invocations; providers receive a terminal `target_update_required` envelope
instructing the user to update ShipAgent. Tool inputs are never sent to a
runtime that cannot interpret them.
