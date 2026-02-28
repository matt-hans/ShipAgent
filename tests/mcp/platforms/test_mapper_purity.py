# tests/mcp/platforms/test_mapper_purity.py
"""Verify mapper modules are pure — no FastMCP or server imports."""
import importlib
import sys
import pytest


MAPPER_MODULES = [
    "src.mcp.platforms.shopify.mapper",
    # Add new platforms here as they're extracted
]


@pytest.mark.parametrize("module_path", MAPPER_MODULES)
def test_mapper_does_not_import_fastmcp(module_path):
    """Mapper modules must not pull in FastMCP or server dependencies."""
    # Clear any cached imports to get a clean check
    mod = importlib.import_module(module_path)
    imported = set(sys.modules.keys())
    fastmcp_imports = [m for m in imported if "fastmcp" in m.lower() or "mcp.server" in m]
    assert not fastmcp_imports, (
        f"{module_path} transitively imports FastMCP/server modules: {fastmcp_imports}"
    )


@pytest.mark.parametrize("module_path", MAPPER_MODULES)
def test_mapper_does_not_import_its_own_server(module_path):
    """Mapper must not import the server module from its own package."""
    mod = importlib.import_module(module_path)
    # Check that the corresponding server module was not imported
    server_module = module_path.rsplit(".", 1)[0] + ".server"
    assert server_module not in sys.modules, (
        f"{module_path} imported its own server module: {server_module}"
    )
