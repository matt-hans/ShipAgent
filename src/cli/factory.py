"""Client factory for selecting HTTP or in-process backend.

The factory pattern ensures CLI commands never import concrete
implementations directly. The --standalone flag selects the backend.
"""

from src.cli.config import ShipAgentConfig


def get_client(
    standalone: bool = False,
    base_url: str | None = None,
    config: ShipAgentConfig | None = None,
):
    """Create the appropriate ShipAgentClient implementation.

    Args:
        standalone: If True, returns InProcessRunner (runs agent stack in-process).
                    If False, returns HttpClient (talks to daemon over HTTP).
        base_url: Custom daemon URL for HTTP mode. Defaults to http://127.0.0.1:8000.
        config: Loaded config for resolving daemon URL and other settings.

    Returns:
        A ShipAgentClient implementation (HttpClient or InProcessRunner).
    """
    if standalone:
        from src.cli.runner import InProcessRunner
        return InProcessRunner(config=config)
    else:
        if base_url is None:
            if config and config.daemon:
                base_url = f"http://{config.daemon.host}:{config.daemon.port}"
            else:
                base_url = "http://127.0.0.1:8000"
        from src.cli.http_client import HttpClient
        return HttpClient(base_url=base_url)
