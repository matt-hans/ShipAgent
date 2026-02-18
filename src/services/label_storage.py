"""Label storage backends for shipment labels.

Provides a pluggable storage interface so labels are not tied to an
ephemeral local filesystem in containerized deployments.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)
_s3_lifecycle_warning_emitted = False


class LabelStorage(Protocol):
    """Storage contract used by BatchEngine for label persistence."""

    def save_final(
        self,
        tracking_number: str,
        pdf_bytes: bytes,
        job_id: str = "",
        row_number: int = 0,
    ) -> str:
        """Persist a final label and return a storage reference."""

    def save_staged(
        self,
        tracking_number: str,
        pdf_bytes: bytes,
        job_id: str,
        row_number: int,
    ) -> str:
        """Persist a staged label and return a storage reference."""

    def promote(self, staged_ref: str) -> str:
        """Promote a staged label to final storage and return final reference."""

    def exists(self, ref: str) -> bool:
        """Return True when the referenced label exists."""


def _build_label_filename(
    tracking_number: str,
    job_id: str = "",
    row_number: int = 0,
) -> str:
    """Build deterministic label filename for a row."""
    job_prefix = job_id[:8] if job_id else "unknown"
    return f"{job_prefix}_row{row_number:03d}_{tracking_number}.pdf"


def _warn_s3_staging_lifecycle(prefix: str) -> None:
    """Emit a one-time ops warning for staged-label expiration policy."""
    global _s3_lifecycle_warning_emitted
    if _s3_lifecycle_warning_emitted:
        return
    normalized_prefix = prefix.strip("/")
    staging_prefix = (
        f"{normalized_prefix}/staging/"
        if normalized_prefix
        else "staging/"
    )
    logger.warning(
        "S3 label staging cleanup is delegated to bucket lifecycle policy. "
        "Configure expiration for prefix '%s' (for example 1-7 days).",
        staging_prefix,
    )
    _s3_lifecycle_warning_emitted = True


class LocalLabelStorage:
    """Filesystem-backed label storage."""

    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)

    def save_final(
        self,
        tracking_number: str,
        pdf_bytes: bytes,
        job_id: str = "",
        row_number: int = 0,
    ) -> str:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        filename = _build_label_filename(
            tracking_number=tracking_number,
            job_id=job_id,
            row_number=row_number,
        )
        path = self.base_dir / filename
        path.write_bytes(pdf_bytes)
        return str(path)

    def save_staged(
        self,
        tracking_number: str,
        pdf_bytes: bytes,
        job_id: str,
        row_number: int,
    ) -> str:
        staging_dir = self.base_dir / "staging" / job_id
        staging_dir.mkdir(parents=True, exist_ok=True)
        filename = _build_label_filename(
            tracking_number=tracking_number,
            job_id=job_id,
            row_number=row_number,
        )
        path = staging_dir / filename
        path.write_bytes(pdf_bytes)
        return str(path)

    def promote(self, staged_ref: str) -> str:
        staging_path = Path(staged_ref)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        final_path = self.base_dir / staging_path.name
        os.rename(str(staging_path), str(final_path))
        return str(final_path)

    def exists(self, ref: str) -> bool:
        return Path(ref).exists()


class S3LabelStorage:
    """S3-backed label storage for durable label persistence."""

    def __init__(
        self,
        bucket: str,
        prefix: str = "labels",
        region_name: str | None = None,
        endpoint_url: str | None = None,
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.region_name = region_name
        self.endpoint_url = endpoint_url
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError(
                "LABEL_STORAGE_BACKEND=s3 requires boto3. "
                "Install boto3 or switch LABEL_STORAGE_BACKEND=local."
            ) from exc
        self._client = boto3.client(
            "s3",
            region_name=self.region_name,
            endpoint_url=self.endpoint_url,
        )
        return self._client

    def _uri(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"

    def _key_from_ref(self, ref: str) -> str:
        prefix = f"s3://{self.bucket}/"
        if ref.startswith(prefix):
            return ref[len(prefix):]
        return ref.lstrip("/")

    def _final_key(self, filename: str) -> str:
        if self.prefix:
            return f"{self.prefix}/{filename}"
        return filename

    def save_final(
        self,
        tracking_number: str,
        pdf_bytes: bytes,
        job_id: str = "",
        row_number: int = 0,
    ) -> str:
        filename = _build_label_filename(
            tracking_number=tracking_number,
            job_id=job_id,
            row_number=row_number,
        )
        key = self._final_key(filename)
        self._get_client().put_object(
            Bucket=self.bucket,
            Key=key,
            Body=pdf_bytes,
            ContentType="application/pdf",
        )
        return self._uri(key)

    def save_staged(
        self,
        tracking_number: str,
        pdf_bytes: bytes,
        job_id: str,
        row_number: int,
    ) -> str:
        filename = _build_label_filename(
            tracking_number=tracking_number,
            job_id=job_id,
            row_number=row_number,
        )
        staged_key = ""
        if self.prefix:
            staged_key = f"{self.prefix}/staging/{job_id}/{filename}"
        else:
            staged_key = f"staging/{job_id}/{filename}"
        self._get_client().put_object(
            Bucket=self.bucket,
            Key=staged_key,
            Body=pdf_bytes,
            ContentType="application/pdf",
        )
        return self._uri(staged_key)

    def promote(self, staged_ref: str) -> str:
        staged_key = self._key_from_ref(staged_ref)
        filename = staged_key.rsplit("/", 1)[-1]
        final_key = self._final_key(filename)
        client = self._get_client()
        client.copy_object(
            Bucket=self.bucket,
            Key=final_key,
            CopySource={"Bucket": self.bucket, "Key": staged_key},
        )
        client.delete_object(Bucket=self.bucket, Key=staged_key)
        return self._uri(final_key)

    def exists(self, ref: str) -> bool:
        key = self._key_from_ref(ref)
        try:
            self._get_client().head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False


def build_label_storage(local_labels_dir: str | Path) -> LabelStorage:
    """Build label storage backend from environment configuration."""
    backend = os.environ.get("LABEL_STORAGE_BACKEND", "local").strip().lower()
    if backend in {"", "local"}:
        return LocalLabelStorage(local_labels_dir)
    if backend == "s3":
        bucket = os.environ.get("LABEL_STORAGE_S3_BUCKET", "").strip()
        if not bucket:
            raise RuntimeError(
                "LABEL_STORAGE_BACKEND=s3 requires LABEL_STORAGE_S3_BUCKET."
            )
        prefix = os.environ.get("LABEL_STORAGE_S3_PREFIX", "labels")
        _warn_s3_staging_lifecycle(prefix)
        region = os.environ.get("LABEL_STORAGE_S3_REGION", "").strip() or None
        endpoint = os.environ.get("LABEL_STORAGE_S3_ENDPOINT", "").strip() or None
        return S3LabelStorage(
            bucket=bucket,
            prefix=prefix,
            region_name=region,
            endpoint_url=endpoint,
        )
    raise RuntimeError(
        f"Unsupported LABEL_STORAGE_BACKEND={backend!r}. Use 'local' or 's3'."
    )
