"""Add strictly structured authorization evidence and explicit legal holds."""

import sqlalchemy as sa

from alembic import context, op

revision = "20261007_0004"
down_revision = "20260723_0003"
branch_labels = None
depends_on = None


def _schema():
    return context.config.attributes.get("shipagent_control_plane_schema")


def upgrade():
    schema = _schema()
    columns = [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_type", sa.String(96), nullable=False),
        sa.Column("account_id", sa.String(36), nullable=False),
        sa.Column("provider_connection_id", sa.String(36), nullable=False),
        sa.Column("approval_request_id", sa.String(128), nullable=False),
        sa.Column("preview_hash", sa.String(64), nullable=False),
        sa.Column("purchase_scope_hash", sa.String(64), nullable=False),
        sa.Column("authorized_amount_minor", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("approving_subject_hash", sa.String(64), nullable=True),
        sa.Column("execution_target_fingerprint_hash", sa.String(64), nullable=True),
        sa.Column("grant_transition", sa.String(64), nullable=True),
        sa.Column("idempotency_key_hash", sa.String(64), nullable=True),
        sa.Column("result_category", sa.String(64), nullable=True),
        sa.Column("correlation_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "authorized_amount_minor >= 0", name="ck_ledger_nonnegative_amount"
        ),
        sa.CheckConstraint(
            "(authorized_amount_minor IS NULL AND currency IS NULL) OR (authorized_amount_minor IS NOT NULL AND currency IS NOT NULL)",
            name="ck_ledger_amount_currency_pair",
        ),
    ]
    op.create_table("authorization_ledger_events", *columns, schema=schema)
    for field in (
        "event_type",
        "account_id",
        "provider_connection_id",
        "approval_request_id",
        "correlation_id",
        "created_at",
    ):
        op.create_index(
            f"ix_authorization_ledger_events_{field}",
            "authorization_ledger_events",
            [field],
            schema=schema,
        )
    op.create_table(
        "legal_holds",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), nullable=False),
        sa.Column("reason_hash", sa.String(64), nullable=False),
        sa.Column("created_by_actor_hash", sa.String(64), nullable=False),
        sa.Column("released_by_actor_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        schema=schema,
    )
    for field in ("account_id", "created_at", "released_at"):
        op.create_index(
            f"ix_legal_holds_{field}", "legal_holds", [field], schema=schema
        )


def downgrade():
    op.drop_table("legal_holds", schema=_schema())
    op.drop_table("authorization_ledger_events", schema=_schema())
