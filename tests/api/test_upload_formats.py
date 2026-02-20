"""Test that the upload endpoint accepts all supported file formats."""

import pytest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


SUPPORTED_EXTENSIONS = [
    ".csv", ".tsv", ".ssv", ".txt", ".dat",
    ".xlsx", ".xls",
    ".json", ".xml",
    ".edi", ".x12",
    ".fwf",
]


class TestUploadFormatAcceptance:
    """Verify the upload route accepts all new file extensions."""

    @pytest.fixture()
    def client(self):
        """Create a test client for the FastAPI app."""
        from src.api.main import app

        return TestClient(app)

    @pytest.mark.parametrize("ext", SUPPORTED_EXTENSIONS)
    def test_extension_accepted(self, ext, client, tmp_path):
        """Upload endpoint should not reject supported extensions."""
        f = tmp_path / f"test{ext}"
        f.write_text("name,city\nJohn,Dallas")

        with patch("src.api.routes.data_sources.get_data_gateway") as mock_gw:
            gw_instance = AsyncMock()
            mock_gw.return_value = gw_instance

            # Mock both legacy methods and the universal call_tool
            gw_instance.import_csv = AsyncMock(return_value={
                "row_count": 1, "columns": [], "warnings": [],
                "source_type": "delimited", "deterministic_ready": True,
                "row_key_strategy": "source_row_num", "row_key_columns": [],
            })
            gw_instance.import_excel = AsyncMock(return_value={
                "row_count": 1, "columns": [], "warnings": [],
                "source_type": "excel", "deterministic_ready": True,
                "row_key_strategy": "source_row_num", "row_key_columns": [],
            })
            gw_instance._call_tool = AsyncMock(return_value={
                "row_count": 1, "columns": [], "warnings": [],
                "source_type": "delimited", "deterministic_ready": True,
                "row_key_strategy": "source_row_num", "row_key_columns": [],
            })

            with open(f, "rb") as fh:
                response = client.post(
                    "/api/v1/data-sources/upload",
                    files={"file": (f.name, fh, "application/octet-stream")},
                )
            # Should NOT be 400 "Unsupported file type"
            assert response.status_code != 400 or "Unsupported" not in response.text
