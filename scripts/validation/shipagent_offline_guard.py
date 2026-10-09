"""Defensive Python socket guard for synthetic tests, NOT a network sandbox.

The disposable qualified venv loads this through its .pth startup hook, even
for env={} children. Native code, Python -S and alternate interpreters can omit
it; tests expose the Python -S limitation without using external networking.
"""

import ipaddress
import socket
import sys


def _local(host):
    if isinstance(host, bytes):
        host = host.decode("ascii", "strict")
    if host in {"localhost", "localhost.localdomain"}:
        return True
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return address.is_loopback
    except (AttributeError, ValueError):
        return False


def _audit(event, args):
    if event in {"socket.connect", "socket.bind", "socket.sendto"}:
        sock, address = args[0], args[-1]
        if sock.family == socket.AF_UNIX:
            return
        if not isinstance(address, tuple) or not address or not _local(address[0]):
            raise PermissionError(
                "offline validation denies non-loopback socket access"
            )
    elif event in {
        "socket.getaddrinfo",
        "socket.gethostbyname",
        "socket.gethostbyaddr",
    }:
        if not _local(args[0]):
            raise PermissionError("offline validation denies external DNS lookup")


sys.addaudithook(_audit)
