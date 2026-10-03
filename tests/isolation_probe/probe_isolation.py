"""Ordered probes for the test-process environment isolation guarantees.

``test_a`` deliberately mutates ``os.environ`` the way a leaky test would;
``test_b`` (collected after it) must observe a clean process. They are run both
in the normal suite and, by ``tests/test_environment_isolation.py``, in a
subprocess whose parent environment is polluted with ShipAgent variables.

The file name deliberately does not match ``test_*.py``: the main suite must
not collect it (``test_c`` is only meaningful with ``SHIPAGENT_TEST_PROBE``
exported), so it runs only when named explicitly by the isolation tests.
"""

import os

import pytest

LEAK_NAME = "SHIPAGENT_API_KEY"
AUTH_AND_LISTENER_SETTINGS = (
    "SHIPAGENT_API_KEY",
    "SHIPAGENT_BIND_HOST",
    "SHIPAGENT_AUTH_MODE",
)


def test_a_direct_environment_mutation_is_confined_to_one_test():
    """Simulate a leaky test that writes a short API key straight to os.environ."""
    os.environ[LEAK_NAME] = "keyring-key"


def test_b_no_auth_or_listener_environment_visible():
    """Neither ambient nor previous-test auth/listener settings are visible."""
    leaked = [name for name in AUTH_AND_LISTENER_SETTINGS if name in os.environ]
    assert leaked == []


def test_c_explicit_test_configuration_is_preserved():
    """SHIPAGENT_TEST_* variables are deliberate test inputs and survive the scrub."""
    if "SHIPAGENT_TEST_PROBE" not in os.environ:
        pytest.skip("only meaningful when the parent exports SHIPAGENT_TEST_PROBE")
    assert os.environ["SHIPAGENT_TEST_PROBE"] == "kept"
