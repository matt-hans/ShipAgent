"""Regression tests for removing hard Claude SDK requirements."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_required_install_does_not_include_claude_agent_sdk():
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text()

    assert "claude-agent-sdk" not in pyproject


def test_required_install_does_not_include_anthropic_sdk():
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text()

    assert "anthropic>=" not in pyproject


def test_backend_start_script_does_not_probe_claude_agent_sdk():
    script = (PROJECT_ROOT / "scripts" / "start-backend.sh").read_text()

    assert "claude_agent_sdk" not in script
    assert "claude-agent-sdk" not in script


def test_pyinstaller_spec_does_not_force_claude_agent_sdk_hidden_import():
    spec = (PROJECT_ROOT / "shipagent-core.spec").read_text()

    assert "'claude_agent_sdk'" not in spec
    assert '"claude_agent_sdk"' not in spec


def test_pyinstaller_spec_does_not_force_anthropic_sdk_hidden_import():
    spec = (PROJECT_ROOT / "shipagent-core.spec").read_text()

    assert "'anthropic'" not in spec
    assert '"anthropic"' not in spec


def test_conversation_runtime_package_does_not_import_claude_sdk_or_hooks():
    runtime_dir = PROJECT_ROOT / "src" / "services" / "conversation_runtime"
    source = "\n".join(path.read_text() for path in runtime_dir.glob("*.py"))

    assert "claude_agent_sdk" not in source
    assert "src.orchestrator.agent.hooks" not in source


def test_active_non_compat_source_does_not_import_claude_agent_sdk_after_runtime_split():
    source_roots = [PROJECT_ROOT / "src" / "services"]
    combined = []
    for root in source_roots:
        for path in root.rglob("*.py"):
            if path.name == "__pycache__":
                continue
            combined.append(path.read_text())
    source = "\n".join(combined)

    assert "claude_agent_sdk" not in source


def test_conversation_runtime_imports_do_not_load_claude_sdk_or_hooks():
    code = """
import builtins

real_import = builtins.__import__

def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "claude_agent_sdk" or name.startswith("claude_agent_sdk."):
        raise AssertionError(f"runtime imported forbidden Claude SDK module: {name}")
    if name == "src.orchestrator.agent.hooks":
        raise AssertionError("runtime imported src.orchestrator.agent.hooks")
    return real_import(name, globals, locals, fromlist, level)

builtins.__import__ = guarded_import

import src.services.conversation_runtime.models  # noqa: F401
import src.services.conversation_runtime.fake_provider  # noqa: F401
import src.services.conversation_runtime.tool_catalog  # noqa: F401
import src.services.conversation_runtime.policy  # noqa: F401
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_backend_modules_import_when_claude_agent_sdk_is_unavailable():
    code = """
import builtins

real_import = builtins.__import__

def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "claude_agent_sdk" or name.startswith("claude_agent_sdk."):
        raise ModuleNotFoundError("No module named 'claude_agent_sdk'", name="claude_agent_sdk")
    return real_import(name, globals, locals, fromlist, level)

builtins.__import__ = guarded_import

import src.api.main  # noqa: F401
import src.orchestrator.agent.client  # noqa: F401
import src.orchestrator.agent.hooks  # noqa: F401
import src.services.conversation_agent  # noqa: F401
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
