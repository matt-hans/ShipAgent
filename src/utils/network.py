"""Canonical network-address helpers shared by startup, relay and CLI code."""

from __future__ import annotations

import ipaddress


def is_loopback_host(host: str | None) -> bool:
    """Return True only if ``host`` is a literal loopback name or address.

    Accepts ``localhost`` (case/trailing-dot insensitive), IPv4/IPv6 loopback,
    bracketed IPv6, zone-id suffixes and IPv4-mapped loopback. Wildcards
    (``0.0.0.0``, ``::``), empty values and other hostnames are not loopback.
    """
    if not host:
        return False
    value = host.strip().strip("[]").split("%", 1)[0].rstrip(".").lower()
    if value == "localhost":
        return True
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_loopback


def is_non_loopback_peer(address: tuple | None) -> bool:
    """Return True if an ASGI ``(host, port)`` tuple holds a non-loopback IP.

    Non-IP hosts (in-process test clients), missing addresses and Unix-socket
    values are not network peers and return False.
    """
    if not address:
        return False
    value = str(address[0]).strip().strip("[]").split("%", 1)[0]
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return not is_loopback_host(value)
