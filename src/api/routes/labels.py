"""FastAPI routes for label downloads.

Provides REST API endpoints for downloading individual shipping labels
and bulk ZIP downloads of all labels for a job.
"""

from pathlib import Path

import zipstream
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
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

    # Collect valid label paths
    label_paths: list[tuple[str, str]] = []  # (file_path, archive_name)
    for row in rows:
        if row.label_path:
            path = Path(row.label_path)
            if path.exists():
                # Use tracking number or row number for archive name
                name = f"{row.tracking_number}.pdf" if row.tracking_number else f"row_{row.row_number}.pdf"
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
