"""FastAPI routes for label downloads.

Provides REST API endpoints for downloading individual shipping labels,
bulk ZIP downloads, and merged PDF downloads of all labels for a job.
"""

import io
from pathlib import Path

import zipstream
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pypdf import PdfWriter
from sqlalchemy.orm import Session

from src.db.connection import get_db
from src.db.models import Job, JobRow

router = APIRouter(tags=["labels"])


@router.get("/labels/{tracking_number}")
def get_label(
    tracking_number: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    """Download an individual shipping label by tracking number.

    Looks up the label file path from the job row and returns the PDF file.
    Returns 404 if the tracking number is not found or the label file is missing.

    Args:
        tracking_number: UPS tracking number for the shipment.
        db: Database session dependency.

    Returns:
        FileResponse with the PDF label file.

    Raises:
        HTTPException: If tracking number not found (404) or label file missing (404).
    """
    # Find the job row with this tracking number
    row = (
        db.query(JobRow)
        .filter(JobRow.tracking_number == tracking_number)
        .first()
    )

    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Tracking number not found: {tracking_number}",
        )

    if not row.label_path:
        raise HTTPException(
            status_code=404,
            detail=f"No label available for tracking number: {tracking_number}",
        )

    # Verify file exists
    label_path = Path(row.label_path)
    if not label_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Label file not found for tracking number: {tracking_number}",
        )

    return FileResponse(
        path=str(label_path),
        media_type="application/pdf",
        filename=f"{tracking_number}.pdf",
    )


@router.get("/jobs/{job_id}/labels/zip")
def download_labels_zip(
    job_id: str,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Download all labels for a job as a ZIP file.

    Streams a ZIP file containing all shipping labels for the specified job.
    Uses zipstream-ng for memory-efficient streaming without loading all
    files into memory at once.

    Args:
        job_id: The job UUID.
        db: Database session dependency.

    Returns:
        StreamingResponse with the ZIP file.

    Raises:
        HTTPException: If job not found (404) or no labels available (404).
    """
    # Verify job exists
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Get all rows with labels
    rows = (
        db.query(JobRow)
        .filter(
            JobRow.job_id == job_id,
            JobRow.label_path.isnot(None),
        )
        .all()
    )

    if not rows:
        raise HTTPException(
            status_code=404,
            detail="No labels available for this job",
        )

    # Collect valid label paths with unique archive names
    label_paths: list[tuple[str, str]] = []  # (file_path, archive_name)
    seen_names: set[str] = set()
    for row in rows:
        if row.label_path:
            path = Path(row.label_path)
            if path.exists():
                # Build archive name with row number prefix for uniqueness
                # (tracking numbers may collide in UPS sandbox)
                tracking = row.tracking_number or "unknown"
                name = f"row{row.row_number:03d}_{tracking}.pdf"
                # Ensure uniqueness even in unexpected edge cases
                if name in seen_names:
                    name = f"row{row.row_number:03d}_{tracking}_{row.id[:8]}.pdf"
                seen_names.add(name)
                label_paths.append((str(path), name))

    if not label_paths:
        raise HTTPException(
            status_code=404,
            detail="No valid label files found for this job",
        )

    def generate_zip():
        """Generator that yields ZIP file chunks."""
        zs = zipstream.ZipFile(mode="w", compression=zipstream.ZIP_STORED)
        for file_path, archive_name in label_paths:
            zs.write(file_path, arcname=archive_name)
        yield from zs

    # Create a sanitized filename for the ZIP
    job_name_slug = "".join(c if c.isalnum() or c in "-_" else "_" for c in job.name[:30])

    return StreamingResponse(
        generate_zip(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="labels-{job_name_slug}-{job_id[:8]}.zip"'
        },
    )


@router.get("/jobs/{job_id}/labels/merged")
def download_labels_merged(
    job_id: str,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Download all labels for a job as a single merged PDF.

    Concatenates all per-row label PDFs into one combined document
    using pypdf.PdfWriter, streamed via an in-memory buffer.

    Args:
        job_id: The job UUID.
        db: Database session dependency.

    Returns:
        StreamingResponse with the merged PDF.

    Raises:
        HTTPException: If job not found (404) or no labels available (404).
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    rows = (
        db.query(JobRow)
        .filter(
            JobRow.job_id == job_id,
            JobRow.label_path.isnot(None),
        )
        .order_by(JobRow.row_number)
        .all()
    )

    if not rows:
        raise HTTPException(
            status_code=404,
            detail="No labels available for this job",
        )

    writer = PdfWriter()
    pages_added = 0

    for row in rows:
        if not row.label_path:
            continue
        path = Path(row.label_path)
        if not path.exists():
            continue
        try:
            writer.append(str(path))
            pages_added += 1
        except Exception:
            # Skip corrupt or unreadable PDFs
            continue

    if pages_added == 0:
        raise HTTPException(
            status_code=404,
            detail="No valid label files found for this job",
        )

    buffer = io.BytesIO()
    writer.write(buffer)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="labels-{job_id[:8]}.pdf"'
        },
    )


@router.get("/jobs/{job_id}/labels/{row_number}")
def get_label_by_row(
    job_id: str,
    row_number: int,
    db: Session = Depends(get_db),
) -> FileResponse:
    """Download an individual label by job ID and row number.

    Provides unambiguous label access when tracking numbers are non-unique
    (e.g. UPS sandbox returns the same masked tracking number for all rows).

    Args:
        job_id: The job UUID.
        row_number: 1-based row number within the job.
        db: Database session dependency.

    Returns:
        FileResponse with the PDF label file.

    Raises:
        HTTPException: If job/row not found (404) or label file missing (404).
    """
    row = (
        db.query(JobRow)
        .filter(JobRow.job_id == job_id, JobRow.row_number == row_number)
        .first()
    )

    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Row {row_number} not found in job {job_id}",
        )

    if not row.label_path:
        raise HTTPException(
            status_code=404,
            detail=f"No label available for row {row_number} in job {job_id}",
        )

    label_path = Path(row.label_path)
    if not label_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Label file not found for row {row_number} in job {job_id}",
        )

    tracking = row.tracking_number or f"row_{row_number}"
    return FileResponse(
        path=str(label_path),
        media_type="application/pdf",
        filename=f"{tracking}_row{row_number}.pdf",
    )
