"""Tests for API main runtime configuration helpers."""

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

