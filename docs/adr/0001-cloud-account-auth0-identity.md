# ADR 0001: ShipAgent Cloud Account And Auth0 Identity

## Status

Accepted

## Decision

Auth0 authenticates humans and issues OAuth grants. ShipAgent owns an opaque
Cloud Account ID mapped one-to-one to the stable Auth0 `sub`. Provider clients are
independently revocable Provider Connections and never define account identity.
