"""Tests for the HotFolderService watchdog."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.cli.config import AutoConfirmRules, WatchFolderConfig
from src.cli.watchdog_service import (
    HotFolderService,
    _ensure_subdirs,
    _get_file_extension,
    _should_process_file,
)


class TestHelpers:
    """Tests for watchdog helper functions."""

    def test_ensure_subdirs_creates_dirs(self, tmp_path):
        """Creates .processing, processed, and failed subdirectories."""
        _ensure_subdirs(str(tmp_path))
        assert (tmp_path / ".processing").is_dir()
        assert (tmp_path / "processed").is_dir()
        assert (tmp_path / "failed").is_dir()

    def test_get_file_extension(self):
        """Returns lowercase file extension."""
        assert _get_file_extension("orders.CSV") == ".csv"
        assert _get_file_extension("data.xlsx") == ".xlsx"
        assert _get_file_extension("readme.txt") == ".txt"

    def test_should_process_file_csv(self):
        """CSV files in allowed types are processable."""
        config = WatchFolderConfig(
            path="./inbox", command="Ship all", file_types=[".csv"]
        )
        assert _should_process_file("orders.csv", config) is True
        assert _should_process_file("orders.xlsx", config) is False

    def test_should_process_file_ignores_hidden(self):
        """Hidden files (dotfiles) are never processed."""
        config = WatchFolderConfig(
            path="./inbox", command="Ship all", file_types=[".csv"]
        )
        assert _should_process_file(".orders.csv", config) is False

    def test_should_process_file_ignores_temp(self):
        """Temp files (ending in ~) are never processed."""
        config = WatchFolderConfig(
            path="./inbox", command="Ship all", file_types=[".csv"]
        )
        assert _should_process_file("orders.csv~", config) is False


class TestHotFolderService:
    """Tests for the HotFolderService lifecycle."""

    def test_init_creates_subdirs(self, tmp_path):
        """Service initialization creates subdirectories."""
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        config = WatchFolderConfig(path=str(inbox), command="Ship all")
        HotFolderService(configs=[config])
        assert (inbox / ".processing").is_dir()
        assert (inbox / "processed").is_dir()
        assert (inbox / "failed").is_dir()

    def test_startup_scan_finds_existing_files(self, tmp_path):
        """Startup scan detects files dropped while daemon was down."""
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        (inbox / "backlog.csv").write_text("col1,col2\na,b")
        config = WatchFolderConfig(path=str(inbox), command="Ship all")
        service = HotFolderService(configs=[config])
        backlog = service.scan_existing_files()
        assert len(backlog) == 1
        assert backlog[0].name == "backlog.csv"

    def test_claim_file_moves_to_processing(self, tmp_path):
        """Claiming a file moves it to .processing/ directory."""
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        _ensure_subdirs(str(inbox))
        csv_file = inbox / "orders.csv"
        csv_file.write_text("data")

        config = WatchFolderConfig(path=str(inbox), command="Ship all")
        service = HotFolderService(configs=[config])
        result = service.claim_file(str(csv_file))

        assert result is not None
        assert not csv_file.exists()
        assert result.parent.name == ".processing"

    def test_complete_file_moves_to_processed(self, tmp_path):
        """Completing a file moves it from .processing/ to processed/."""
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        _ensure_subdirs(str(inbox))
        processing_file = inbox / ".processing" / "orders.csv"
        processing_file.write_text("data")

        config = WatchFolderConfig(path=str(inbox), command="Ship all")
        service = HotFolderService(configs=[config])
        service.complete_file(processing_file)

        assert not processing_file.exists()
        assert (inbox / "processed" / "orders.csv").exists()

    def test_fail_file_moves_to_failed_with_sidecar(self, tmp_path):
        """Failing a file moves it to failed/ with an error sidecar."""
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        _ensure_subdirs(str(inbox))
        processing_file = inbox / ".processing" / "orders.csv"
        processing_file.write_text("data")

        config = WatchFolderConfig(path=str(inbox), command="Ship all")
        service = HotFolderService(configs=[config])
        service.fail_file(processing_file, {"error": "Import failed"})

        assert not processing_file.exists()
        assert (inbox / "failed" / "orders.csv").exists()
        error_file = inbox / "failed" / "orders.csv.error"
        assert error_file.exists()
        error_data = json.loads(error_file.read_text())
        assert error_data["error"] == "Import failed"


class TestProcessWatchedFileEndToEnd:
    """End-to-end tests for _process_watched_file.

    Tests the critical watchdog flow: file claim -> agent processing ->
    auto-confirm evaluation -> execution (or rejection) -> file finalization.
    All external dependencies (agent, data gateway, DB) are mocked.

    IMPORTANT: _process_watched_file guards on `global _watchdog_service`.
    Each test must set this module-level variable (via patch) so the function
    does not early-return. We create a real HotFolderService instance
    backed by the test's tmp_path inbox.
    """

    @pytest.mark.asyncio
    async def test_auto_confirm_approved_executes_and_moves_to_processed(
        self, tmp_path
    ):
        """When auto-confirm approves, job executes and file moves to processed/."""
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        _ensure_subdirs(str(inbox))
        csv_file = inbox / "orders.csv"
        csv_file.write_text("name,city\nJohn,LA")

        config = WatchFolderConfig(
            path=str(inbox),
            command="Ship all orders",
            auto_confirm=True,
            max_cost_cents=100000,
            max_rows=500,
        )

        watchdog_svc = HotFolderService(configs=[config])

        mock_gw = AsyncMock()
        mock_gw.import_csv = AsyncMock(return_value={"success": True, "rows": 1})
        mock_gw.get_source_info_typed = AsyncMock(return_value=None)

        async def fake_process_message(session, content, interactive_shipping=False, **kw):
            yield {"event": "preview_ready", "data": {"job_id": "job-1"}}
            yield {"event": "agent_message", "data": {"text": "Done"}}

        mock_job = MagicMock()
        mock_job.id = "job-1"
        mock_job.status = "pending"
        mock_job.shipper_json = None
        mock_row = MagicMock()
        mock_row.cost_cents = 1500
        mock_row.order_data = '{"service_code": "03"}'

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_job
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_row]

        mock_global_config = MagicMock()
        mock_global_config.auto_confirm = AutoConfirmRules(
            enabled=True,
            require_valid_addresses=False,
            allowed_services=[],
        )

        with (
            patch("src.api.main._watchdog_service", watchdog_svc),
            patch("src.services.gateway_provider.get_data_gateway", new_callable=AsyncMock, return_value=mock_gw),
            patch("src.services.conversation_handler.process_message", side_effect=fake_process_message),
            patch("src.services.conversation_handler.ensure_agent", new_callable=AsyncMock),
            patch("src.services.batch_executor.execute_batch", new_callable=AsyncMock) as mock_exec,
            patch("src.db.connection.get_db", return_value=iter([mock_db])),
            patch("src.cli.config.load_config", return_value=mock_global_config),
        ):
            from src.api.main import _process_watched_file
            await _process_watched_file(str(csv_file), config)

        assert not csv_file.exists()
        assert (inbox / "processed" / "orders.csv").exists()
        mock_exec.assert_called_once()

    @pytest.mark.asyncio
    async def test_auto_confirm_rejected_leaves_job_pending(self, tmp_path):
        """When auto-confirm rejects, job stays pending and file moves to processed/."""
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        _ensure_subdirs(str(inbox))
        csv_file = inbox / "orders.csv"
        csv_file.write_text("name,city\nJohn,LA")

        config = WatchFolderConfig(
            path=str(inbox),
            command="Ship all orders",
            auto_confirm=True,
            max_cost_cents=100,  # Very low threshold — will reject
            max_rows=500,
        )

        watchdog_svc = HotFolderService(configs=[config])

        mock_row = MagicMock()
        mock_row.cost_cents = 50000  # $500 > $1 limit
        mock_row.order_data = '{"service_code": "03"}'

        mock_job = MagicMock()
        mock_job.id = "job-1"
        mock_job.status = "pending"
        mock_job.shipper_json = None

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_job
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_row]

        mock_gw = AsyncMock()
        mock_gw.import_csv = AsyncMock(return_value={"success": True, "rows": 1})
        mock_gw.get_source_info_typed = AsyncMock(return_value=None)

        async def fake_process_message(session, content, interactive_shipping=False, **kw):
            yield {"event": "preview_ready", "data": {"job_id": "job-1"}}

        with (
            patch("src.api.main._watchdog_service", watchdog_svc),
            patch("src.services.gateway_provider.get_data_gateway", new_callable=AsyncMock, return_value=mock_gw),
            patch("src.services.conversation_handler.process_message", side_effect=fake_process_message),
            patch("src.services.conversation_handler.ensure_agent", new_callable=AsyncMock),
            patch("src.services.batch_executor.execute_batch", new_callable=AsyncMock) as mock_exec,
            patch("src.db.connection.get_db", return_value=iter([mock_db])),
        ):
            from src.api.main import _process_watched_file
            await _process_watched_file(str(csv_file), config)

        mock_exec.assert_not_called()
        assert mock_job.status == "pending"

    @pytest.mark.asyncio
    async def test_processing_error_moves_file_to_failed(self, tmp_path):
        """When processing fails, file moves to failed/ with error sidecar."""
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        _ensure_subdirs(str(inbox))
        csv_file = inbox / "orders.csv"
        csv_file.write_text("bad data")

        config = WatchFolderConfig(
            path=str(inbox),
            command="Ship all orders",
            auto_confirm=False,
        )

        watchdog_svc = HotFolderService(configs=[config])

        mock_gw = AsyncMock()
        mock_gw.import_csv = AsyncMock(side_effect=Exception("Import failed"))

        with (
            patch("src.api.main._watchdog_service", watchdog_svc),
            patch("src.services.gateway_provider.get_data_gateway", new_callable=AsyncMock, return_value=mock_gw),
        ):
            from src.api.main import _process_watched_file
            await _process_watched_file(str(csv_file), config)

        assert not csv_file.exists()
        assert (inbox / "failed" / "orders.csv").exists()
        assert (inbox / "failed" / "orders.csv.error").exists()

    @pytest.mark.asyncio
    async def test_global_lock_serializes_concurrent_files(self, tmp_path):
        """Only one file processes at a time across all watch folders."""
        inbox1 = tmp_path / "inbox1"
        inbox2 = tmp_path / "inbox2"
        inbox1.mkdir()
        inbox2.mkdir()
        _ensure_subdirs(str(inbox1))
        _ensure_subdirs(str(inbox2))

        (inbox1 / "a.csv").write_text("data")
        (inbox2 / "b.csv").write_text("data")

        config1 = WatchFolderConfig(path=str(inbox1), command="Ship")
        config2 = WatchFolderConfig(path=str(inbox2), command="Ship")

        watchdog_svc = HotFolderService(configs=[config1, config2])

        processing_order = []

        async def fake_import(*args, **kwargs):
            processing_order.append("start")
            await asyncio.sleep(0.1)
            processing_order.append("end")
            return {"success": True, "rows": 1}

        mock_gw = AsyncMock()
        mock_gw.import_csv = fake_import
        mock_gw.get_source_info_typed = AsyncMock(return_value=None)

        async def fake_process_message(session, content, interactive_shipping=False, **kw):
            yield {"event": "agent_message", "data": {"text": "Done"}}

        with (
            patch("src.api.main._watchdog_service", watchdog_svc),
            patch("src.services.gateway_provider.get_data_gateway", new_callable=AsyncMock, return_value=mock_gw),
            patch("src.services.conversation_handler.process_message", side_effect=fake_process_message),
            patch("src.services.conversation_handler.ensure_agent", new_callable=AsyncMock),
        ):
            from src.api.main import _process_watched_file
            await asyncio.gather(
                _process_watched_file(str(inbox1 / "a.csv"), config1),
                _process_watched_file(str(inbox2 / "b.csv"), config2),
            )

        # With global lock: start, end, start, end (serialized)
        assert processing_order == ["start", "end", "start", "end"]
