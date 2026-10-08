"""Pure contract guards, with no service or provider dependencies."""

import pytest

from src.control_plane.relay.lifecycle import TimeoutLadder


@pytest.mark.parametrize(
    "updates",
    [
        {"cloud_send_seconds": 0},
        {"cloud_send_seconds": True},
        {"cloud_send_seconds": float("nan")},
        {"target_accept_seconds": 5.1},
        {"sync_hard_deadline_seconds": 26},
        {"sync_hard_deadline_seconds": 7},
        {"poll_after_ms": True},
        {"poll_after_ms": 99},
    ],
)
def test_timeout_configuration_cannot_exceed_accepted_ladder(updates):
    with pytest.raises(ValueError):
        TimeoutLadder(**updates)
