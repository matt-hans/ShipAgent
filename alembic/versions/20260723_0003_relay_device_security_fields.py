"""Add relay device key version and revocation timestamp."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260723_0003"
down_revision = "20260630_0002"
branch_labels = None
depends_on = None


def _schema() -> str | None:
    from alembic import context
    from src.control_plane.db import resolve_control_plane_schema

    if "shipagent_control_plane_schema" in context.config.attributes:
        return context.config.attributes["shipagent_control_plane_schema"]
    runtime_section = context.config.get_section("alembic:runtime") or {}
    return resolve_control_plane_schema(
        dialect_name=op.get_context().dialect.name,
        configured_schema=runtime_section.get("shipagent_control_plane_schema"),
    )


def upgrade() -> None:
    schema = _schema()
    op.add_column(
        "relay_devices",
        sa.Column(
            "key_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        schema=schema,
    )
    op.add_column(
        "relay_devices",
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        schema=schema,
    )


def downgrade() -> None:
    schema = _schema()
    op.drop_column("relay_devices", "revoked_at", schema=schema)
    op.drop_column("relay_devices", "key_version", schema=schema)
