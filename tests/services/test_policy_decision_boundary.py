"""The neutral policy boundary must stay free of vendor frameworks/envelopes."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2] / "src" / "services"
_NEUTRAL_MODULES = [
    _ROOT / "policy_decision.py",
    _ROOT / "conversation_runtime" / "policy.py",
    _ROOT / "conversation_runtime" / "dispatcher.py",
]
_VENDOR_ROOTS = {"claude_agent_sdk", "anthropic", "openai", "google"}
_ENVELOPE_MARKERS = ("hookSpecificOutput", "permissionDecision", "PreToolUse")


@pytest.mark.parametrize("path", _NEUTRAL_MODULES, ids=lambda p: p.name)
def test_neutral_policy_modules_import_no_vendor_framework(path: Path) -> None:
    tree = ast.parse(path.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])

    assert imported.isdisjoint(_VENDOR_ROOTS)
    assert "src.orchestrator.agent.hooks" not in {
        n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
    }


@pytest.mark.parametrize("path", _NEUTRAL_MODULES, ids=lambda p: p.name)
def test_neutral_policy_modules_do_not_build_claude_hook_envelopes(path: Path) -> None:
    source = path.read_text()

    assert not any(marker in source for marker in _ENVELOPE_MARKERS)
