# tests/mcp/platforms/test_mapper_purity.py
"""Verify mapper modules are pure — no FastMCP or server imports."""
import importlib
import sys
import pytest


MAPPER_MODULES = [
    "src.mcp.platforms.shopify.mapper",
    "src.mcp.platforms.dummy.mapper",
    "src.mcp.platforms.woocommerce.mapper",
    "src.mcp.platforms.sap.mapper",
    "src.mcp.platforms.amazon.mapper",
    # Add new platforms here as they're extracted
]


@pytest.mark.parametrize("module_path", MAPPER_MODULES)
def test_mapper_does_not_import_fastmcp(module_path):
    """Mapper modules must not pull in FastMCP or server dependencies.

    Uses before/after snapshot of sys.modules to be robust against
    test ordering (other tests may load fastmcp before this one runs).
    """
    before = set(sys.modules.keys())
    importlib.import_module(module_path)
    after = set(sys.modules.keys())

    newly_imported = after - before
    fastmcp_imports = [m for m in newly_imported if "fastmcp" in m.lower() or "mcp.server" in m]
    assert not fastmcp_imports, (
        f"{module_path} transitively imports FastMCP/server modules: {fastmcp_imports}"
    )


@pytest.mark.parametrize("module_path", MAPPER_MODULES)
def test_mapper_does_not_import_its_own_server(module_path):
    """Mapper must not import the server module from its own package."""
    before = set(sys.modules.keys())
    importlib.import_module(module_path)
    after = set(sys.modules.keys())

    newly_imported = after - before
    server_module = module_path.rsplit(".", 1)[0] + ".server"
    assert server_module not in newly_imported, (
        f"{module_path} imported its own server module: {server_module}"
    )
