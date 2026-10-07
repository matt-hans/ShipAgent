"""Run real upload-to-MCP imports with an isolated configured data directory."""

import asyncio
import os
from pathlib import Path

import httpx


async def main():
    from src.api.main import app
    from src.api.routes.data_sources import UPLOAD_DIR

    data = Path(os.environ["SHIPAGENT_DATA_DIR"])
    assert UPLOAD_DIR == data / "uploads", UPLOAD_DIR
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as api:
            uploaded = await api.post(
                "/api/v1/data-sources/upload",
                files={"file": ("synthetic.csv", b"name,city\nAlice Example,Springfield\nBob Example,Shelbyville\n", "text/csv")},
            )
            assert uploaded.status_code == 200, uploaded.text
            assert uploaded.json()["status"] == "connected", uploaded.text
            assert uploaded.json()["row_count"] == 2, uploaded.text
            assert (UPLOAD_DIR / "synthetic.csv").is_file()
            # A writable app-data root must not authorize sibling settings/keys.
            outside = data / "outside.csv"
            outside.write_text("name\nUNAUTHORIZED_CANARY\n")
            secret = UPLOAD_DIR / ".env"
            secret.write_text("SYNTHETIC_SECRET=DO_NOT_READ\n")
            escape = UPLOAD_DIR / "escape.csv"
            escape.symlink_to(outside)
            for path in (outside, secret, escape):
                denied = await api.post(
                    "/api/v1/data-sources/import", json={"type": "csv", "file_path": str(path)}
                )
                assert denied.json()["status"] == "error", denied.text
            status = await api.get("/api/v1/data-sources/status")
            assert status.json()["row_count"] == 2, status.text
    print("ISOLATED_UPLOAD_MCP_AND_PATH_DENIALS_OK")


if __name__ == "__main__":
    asyncio.run(main())
