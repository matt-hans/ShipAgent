"""Idempotency key generation for exactly-once shipment creation."""


def generate_idempotency_key(job_id: str, row_number: int, row_checksum: str) -> str:
    """Generate a deterministic idempotency key for a shipment row.

    The key uniquely identifies a specific row in a specific job with a specific
    data snapshot. If the row data changes (different checksum), the key changes,
    allowing a new shipment to be created for the updated data.

    Args:
        job_id: UUID of the parent job.
        row_number: 1-based row number in the job.
        row_checksum: MD5 hash of the row's order_data JSON.

    Returns:
        Idempotency key string: '{job_id}:{row_number}:{row_checksum}'.
    """
    return f"{job_id}:{row_number}:{row_checksum}"
