"""Service for persisting and reconnecting data source connections.

Saves display metadata for every connected data source so users can
reconnect with one click. File-based sources (CSV/Excel) store the
server-side file path. Database sources store only display info — no
credentials are ever persisted.

Example:
    with get_db_context() as db:
        sources = SavedDataSourceService.list_sources(db)
        SavedDataSourceService.save_or_update_csv(db, "/uploads/orders.csv", 150, 12)
"""

import logging
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import desc
from sqlalchemy.orm import Session

from src.db.models import SavedDataSource, utc_now_iso

logger = logging.getLogger(__name__)


def parse_db_connection_string(conn_str: str) -> dict[str, str | int | None]:
    """Extract display-safe fields from a database connection URL.

    Parses host, port, and database name from a standard connection URL.
    Never stores username, password, or full connection string.

    Args:
        conn_str: Database connection URL (e.g. postgresql://user:pass@host:5432/mydb).

    Returns:
        Dict with 'host', 'port', and 'db_name' keys.
    """
    parsed = urlparse(conn_str)
    return {
        "host": parsed.hostname,
        "port": parsed.port,
        "db_name": parsed.path.lstrip("/") if parsed.path else None,
    }


class SavedDataSourceService:
    """CRUD operations for saved data source records.

    All methods are static and accept a SQLAlchemy session, matching
    the existing service pattern used throughout ShipAgent.
    """

    @staticmethod
    def list_sources(
        db: Session,
        source_type: str | None = None,
    ) -> list[SavedDataSource]:
        """List saved data sources, ordered by most recently used.

        Args:
            db: SQLAlchemy session.
            source_type: Optional filter ('csv', 'excel', 'database').

        Returns:
            List of SavedDataSource records.
        """
        query = db.query(SavedDataSource).order_by(
            desc(SavedDataSource.last_used_at)
        )
        if source_type:
            query = query.filter(SavedDataSource.source_type == source_type)
        return query.all()

    @staticmethod
    def get_source(db: Session, source_id: str) -> SavedDataSource | None:
        """Fetch a single saved data source by ID.

        Args:
            db: SQLAlchemy session.
            source_id: UUID of the saved source.

        Returns:
            SavedDataSource if found, None otherwise.
        """
        return db.query(SavedDataSource).filter(
            SavedDataSource.id == source_id
        ).first()

    @staticmethod
    def save_or_update_csv(
        db: Session,
        file_path: str,
        row_count: int,
        column_count: int,
    ) -> SavedDataSource:
        """Upsert a CSV data source record (keyed by file_path).

        Args:
            db: SQLAlchemy session.
            file_path: Absolute server-side path to the CSV file.
            row_count: Number of rows imported.
            column_count: Number of columns discovered.

        Returns:
            The created or updated SavedDataSource.
        """
        existing = db.query(SavedDataSource).filter(
            SavedDataSource.source_type == "csv",
            SavedDataSource.file_path == file_path,
        ).first()

        name = Path(file_path).name

        if existing:
            existing.row_count = row_count
            existing.column_count = column_count
            existing.last_used_at = utc_now_iso()
            existing.name = name
            db.flush()
            logger.info("Updated saved CSV source: %s", name)
            return existing

        record = SavedDataSource(
            name=name,
            source_type="csv",
            file_path=file_path,
            row_count=row_count,
            column_count=column_count,
        )
        db.add(record)
        db.flush()
        logger.info("Saved new CSV source: %s", name)
        return record

    @staticmethod
    def save_or_update_excel(
        db: Session,
        file_path: str,
        sheet_name: str | None,
        row_count: int,
        column_count: int,
    ) -> SavedDataSource:
        """Upsert an Excel data source record (keyed by file_path + sheet).

        Args:
            db: SQLAlchemy session.
            file_path: Absolute server-side path to the Excel file.
            sheet_name: Sheet name (None for default/first sheet).
            row_count: Number of rows imported.
            column_count: Number of columns discovered.

        Returns:
            The created or updated SavedDataSource.
        """
        query = db.query(SavedDataSource).filter(
            SavedDataSource.source_type == "excel",
            SavedDataSource.file_path == file_path,
        )
        if sheet_name:
            query = query.filter(SavedDataSource.sheet_name == sheet_name)
        else:
            query = query.filter(SavedDataSource.sheet_name.is_(None))
        existing = query.first()

        name = Path(file_path).name
        if sheet_name:
            name = f"{name} ({sheet_name})"

        if existing:
            existing.row_count = row_count
            existing.column_count = column_count
            existing.last_used_at = utc_now_iso()
            existing.name = name
            db.flush()
            logger.info("Updated saved Excel source: %s", name)
            return existing

        record = SavedDataSource(
            name=name,
            source_type="excel",
            file_path=file_path,
            sheet_name=sheet_name,
            row_count=row_count,
            column_count=column_count,
        )
        db.add(record)
        db.flush()
        logger.info("Saved new Excel source: %s", name)
        return record

    @staticmethod
    def save_or_update_database(
        db: Session,
        host: str | None,
        port: int | None,
        db_name: str | None,
        query: str,
        row_count: int,
        column_count: int,
    ) -> SavedDataSource:
        """Upsert a database data source record (keyed by host + db_name + query).

        Args:
            db: SQLAlchemy session.
            host: Database hostname (display only).
            port: Database port (display only).
            db_name: Database name (display only).
            query: SQL query used for import.
            row_count: Number of rows imported.
            column_count: Number of columns discovered.

        Returns:
            The created or updated SavedDataSource.
        """
        existing = db.query(SavedDataSource).filter(
            SavedDataSource.source_type == "database",
            SavedDataSource.db_host == host,
            SavedDataSource.db_name == db_name,
            SavedDataSource.db_query == query,
        ).first()

        name = f"{db_name}@{host}" if host and db_name else (db_name or host or "Database")

        if existing:
            existing.row_count = row_count
            existing.column_count = column_count
            existing.db_port = port
            existing.last_used_at = utc_now_iso()
            existing.name = name
            db.flush()
            logger.info("Updated saved database source: %s", name)
            return existing

        record = SavedDataSource(
            name=name,
            source_type="database",
            db_host=host,
            db_port=port,
            db_name=db_name,
            db_query=query,
            row_count=row_count,
            column_count=column_count,
        )
        db.add(record)
        db.flush()
        logger.info("Saved new database source: %s", name)
        return record

    @staticmethod
    def delete_source(db: Session, source_id: str) -> bool:
        """Delete a saved data source by ID.

        Args:
            db: SQLAlchemy session.
            source_id: UUID of the source to delete.

        Returns:
            True if deleted, False if not found.
        """
        record = db.query(SavedDataSource).filter(
            SavedDataSource.id == source_id
        ).first()
        if not record:
            return False
        db.delete(record)
        db.flush()
        logger.info("Deleted saved source: %s", record.name)
        return True

    @staticmethod
    def bulk_delete(db: Session, source_ids: list[str]) -> int:
        """Delete multiple saved data sources by ID.

        Args:
            db: SQLAlchemy session.
            source_ids: List of UUIDs to delete.

        Returns:
            Number of records deleted.
        """
        count = db.query(SavedDataSource).filter(
            SavedDataSource.id.in_(source_ids)
        ).delete(synchronize_session="fetch")
        db.flush()
        logger.info("Bulk deleted %d saved sources", count)
        return count

    @staticmethod
    def touch(db: Session, source_id: str) -> None:
        """Update last_used_at timestamp for a source.

        Args:
            db: SQLAlchemy session.
            source_id: UUID of the source.
        """
        record = db.query(SavedDataSource).filter(
            SavedDataSource.id == source_id
        ).first()
        if record:
            record.last_used_at = utc_now_iso()
            db.flush()
