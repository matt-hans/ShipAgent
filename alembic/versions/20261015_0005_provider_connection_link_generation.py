"""Persist Provider Connection link generation for dormant Agent Run admission."""

import sqlalchemy as sa

from alembic import context, op

revision = "20261015_0005"
down_revision = "20261007_0004"
branch_labels = None
depends_on = None


def _schema():
    return context.config.attributes.get("shipagent_control_plane_schema")


def upgrade():
    with op.batch_alter_table("provider_connections", schema=_schema()) as batch:
        batch.add_column(
            sa.Column(
                "link_generation",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            )
        )
        batch.create_check_constraint(
            "ck_provider_connection_link_generation",
            "link_generation >= 1 AND link_generation <= 2147483647",
        )


def downgrade():
    with op.batch_alter_table("provider_connections", schema=_schema()) as batch:
        batch.drop_constraint("ck_provider_connection_link_generation", type_="check")
        batch.drop_column("link_generation")
