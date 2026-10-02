"""Tests for API main runtime configuration helpers."""

from src.api.browser_origins import configured_browser_origins
from src.api.main import _parse_allowed_origins


def test_parse_allowed_origins_empty(monkeypatch):
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    assert _parse_allowed_origins() == []


def test_parse_allowed_origins_csv(monkeypatch):
    monkeypatch.setenv(
        "ALLOWED_ORIGINS",
        "http://localhost:5173, http://127.0.0.1:5173 ,https://example.com",
    )
    assert _parse_allowed_origins() == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://example.com",
    ]


def test_configured_browser_origins_normalize_dev_and_tauri(monkeypatch):
    monkeypatch.setenv(
        "ALLOWED_ORIGINS",
        "HTTP://LOCALHOST:4200,tauri://LOCALHOST,https://tauri.localhost",
    )

    assert configured_browser_origins() == frozenset(
        {
            ("http", "localhost", 4200),
            ("tauri", "localhost", None),
            ("https", "tauri.localhost", 443),
        }
    )


def test_configured_browser_origins_ignore_malformed_values(monkeypatch):
    monkeypatch.setenv(
        "ALLOWED_ORIGINS",
        "*,https://user@example.com,https://example.com/path,not-an-origin",
    )

    assert configured_browser_origins() == frozenset()
