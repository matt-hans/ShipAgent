# ADR 0002: Relay-First Execution Target

## Status

Accepted

## Decision

Public workflows dispatch through an `ExecutionTarget` protocol. The relay
implementation selects the account's Active Desktop Device. A future SaaS worker
may implement the same protocol without changing public tool contracts. Cloud
storage never contains shipment rows, labels, credentials, or raw UPS payloads in
the relay product.

Once an Execution Target creates a preview, its opaque
`execution_target_id` is bound into the Approval Request, Execution Grant, job
and poll references, and label references. Relay reconnect and device-key
rotation preserve this identity. Replacing the active target invalidates pending
approval; the control plane never reroutes an approved preview to another
target.
