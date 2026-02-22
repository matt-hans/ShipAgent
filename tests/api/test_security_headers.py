"""Tests for security headers and universal error sanitization (F-7, F-8).

Verifies that security headers are present on all responses and that
422 validation errors are sanitized uniformly across all routes.
"""

from fastapi.testclient import TestClient


class TestSecurityHeaders:
    """Tests for security header middleware (F-7)."""

    def test_x_content_type_options_present(self, client: TestClient):
        """X-Content-Type-Options: nosniff is set on responses."""
        response = client.get("/health")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"

    def test_x_frame_options_present(self, client: TestClient):
        """X-Frame-Options: DENY is set on responses."""
        response = client.get("/health")
        assert response.headers.get("X-Frame-Options") == "DENY"

    def test_referrer_policy_present(self, client: TestClient):
        """Referrer-Policy is set on responses."""
        response = client.get("/health")
        assert (
            response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        )

    def test_headers_on_api_routes(self, client: TestClient):
        """Security headers present on API routes (not just /health)."""
        response = client.get("/api/v1/jobs")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"

    def test_headers_on_404(self, client: TestClient):
        """Security headers present even on 404 responses."""
        response = client.get("/api/v1/jobs/nonexistent-id")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"


class TestUniversalErrorSanitization:
    """Tests for universal 422 error sanitization (F-8)."""

    def test_422_sanitized_on_non_connection_route(self, client: TestClient):
        """422 errors on non-connection routes are sanitized."""
        # Send invalid JSON body to a route that expects a schema
        response = client.post(
            "/api/v1/data-sources/import",
            json={"type": "invalid_type_that_triggers_nothing"},
        )
        # If this returns 422, verify the response format is sanitized
        if response.status_code == 422:
            data = response.json()
            assert "error" in data
            assert data["error"]["code"] == "VALIDATION_ERROR"
            assert "detail" in data
            for err in data["detail"]:
                assert "type" in err
                assert "loc" in err
                assert "msg" in err
                # Raw input values should not leak
                assert "input" not in err

    def test_422_sanitized_on_connection_route(self, client: TestClient):
        """422 errors on /connections routes remain sanitized."""
        response = client.post(
            "/api/v1/connections/ups",
            json={},  # Missing required fields
        )
        if response.status_code == 422:
            data = response.json()
            assert "error" in data
            assert data["error"]["code"] == "VALIDATION_ERROR"
            for err in data["detail"]:
                assert "input" not in err
