"""Tests for upload file size limit (F-8, CWE-400).

Verifies that the upload endpoint rejects files exceeding the 50 MB limit,
cleans up partial files, and accepts files within the limit.
"""

import io
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


class TestUploadSizeLimit:
    """Tests for upload file size enforcement."""

    def test_upload_within_size_limit(self, client: TestClient, tmp_path: Path):
        """Small CSV file is accepted (200)."""
        csv_content = b"name,city\nAlice,NYC\nBob,LA\n"
        files = {"file": ("test.csv", io.BytesIO(csv_content), "text/csv")}

        # Mock the gateway to avoid actual MCP calls
        mock_gw = AsyncMock()
        mock_gw.import_file = AsyncMock(
            return_value={
                "source_type": "csv",
                "row_count": 2,
                "columns": [
                    {"name": "name", "type": "VARCHAR"},
                    {"name": "city", "type": "VARCHAR"},
                ],
            }
        )
        with patch(
            "src.api.routes.data_sources.get_data_gateway",
            return_value=mock_gw,
        ):
            response = client.post("/api/v1/data-sources/upload", files=files)

        assert response.status_code == 200

    def test_upload_exceeds_size_limit(self, client: TestClient):
        """File exceeding 50 MB returns 413."""
        from src.api.routes.data_sources import _MAX_UPLOAD_SIZE_BYTES

        # Create a file that exceeds the limit (just over)
        oversize_content = b"x" * (_MAX_UPLOAD_SIZE_BYTES + 1024)
        files = {
            "file": ("big.csv", io.BytesIO(oversize_content), "text/csv")
        }

        response = client.post("/api/v1/data-sources/upload", files=files)

        assert response.status_code == 413
        assert "50 MB" in response.json()["detail"]

    def test_upload_cleanup_on_oversize(self, client: TestClient, tmp_path: Path):
        """Partial file is deleted after rejection."""
        from src.api.routes.data_sources import UPLOAD_DIR, _MAX_UPLOAD_SIZE_BYTES

        oversize_content = b"x" * (_MAX_UPLOAD_SIZE_BYTES + 1024)
        files = {
            "file": ("cleanup_test.csv", io.BytesIO(oversize_content), "text/csv")
        }

        response = client.post("/api/v1/data-sources/upload", files=files)
        assert response.status_code == 413

        # Verify partial file was cleaned up
        expected_path = UPLOAD_DIR / "cleanup_test.csv"
        assert not expected_path.exists()
