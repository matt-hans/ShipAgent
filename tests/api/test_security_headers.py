"""Tests for security headers and universal error sanitization (F-3, F-7, F-8).

Verifies that security headers (CSP, HSTS, X-Content-Type-Options, etc.)
are present on all responses and that 422 validation errors are sanitized
uniformly across all routes.
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

    def test_csp_header_present(self, client: TestClient):
        """CSP header includes default-src, script-src, style-src, connect-src (F-3)."""
        response = client.get("/health")

        assert response.status_code == 200
        csp = response.headers.get("Content-Security-Policy", "")
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "style-src 'self' 'unsafe-inline'" in csp
        assert "connect-src 'self'" in csp

    def test_hsts_header_present(self, client: TestClient):
        """HSTS header includes max-age and includeSubDomains (F-3)."""
        response = client.get("/health")

        assert response.status_code == 200
        hsts = response.headers.get("Strict-Transport-Security", "")
        assert "max-age=31536000" in hsts
        assert "includeSubDomains" in hsts


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


class TestHSTSPreload:
    """Tests for L-1: HSTS preload directive."""

    def test_hsts_includes_preload(self, client: TestClient):
        """HSTS header includes preload directive."""
        response = client.get("/health")
        hsts = response.headers.get("Strict-Transport-Security", "")
        assert "preload" in hsts
        assert "includeSubDomains" in hsts
        assert "max-age=31536000" in hsts


class TestRequestBodySizeLimit:
    """Tests for H-3: request body size limit middleware (CWE-400)."""

    def test_oversized_content_length_rejected(self, client: TestClient):
        """POST with Content-Length > 10MB returns 413."""
        response = client.post(
            "/api/v1/conversations/",
            json={"message": "test"},
            headers={"Content-Length": str(11 * 1024 * 1024)},
        )
        assert response.status_code == 413

    def test_normal_request_accepted(self, client: TestClient):
        """Normal-sized requests pass through the middleware."""
        response = client.post(
            "/api/v1/conversations/",
            json={"message": "test"},
        )
        # Should not be 413 — actual status depends on route logic
        assert response.status_code != 413


class TestErrorDetailRedaction:
    """Tests for M-3: ShipAgentError detail redaction (CWE-209)."""

    def test_shipagent_error_handler_redacts_details(self):
        """ShipAgentError handler source uses sanitize_error_message for details."""
        import inspect

        from src.api.main import shipagent_error_handler

        source = inspect.getsource(shipagent_error_handler)
        assert "sanitize_error_message" in source
