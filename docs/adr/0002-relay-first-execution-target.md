# ADR 0002: Relay-First Execution Target

## Status

Accepted

## Decision

Public workflows dispatch through an `ExecutionTarget` protocol. The relay
implementation selects the account's Active Desktop Device. A future SaaS worker
may implement the same protocol without changing public tool contracts. Cloud
storage never contains shipment rows, labels, credentials, or raw UPS payloads in
the relay product.
