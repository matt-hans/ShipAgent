"""Name the one intentionally unqualified non-loopback listener case."""

import pytest


def pytest_collection_modifyitems(items):
    target = "tests/api/test_listener_guard_socket.py::test_keyless_wildcard_listener_is_closed_to_lan_clients"
    for item in items:
        if item.nodeid == target:
            item.add_marker(
                pytest.mark.skip(
                    reason="offline guard disallows non-loopback LAN listener qualification"
                )
            )
