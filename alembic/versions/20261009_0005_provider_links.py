"""Preserve legacy identities and add explicitly issuer-bound provider links."""

import sqlalchemy as sa

from alembic import context, op

revision = "20261009_0005"
down_revision = "20261007_0004"
branch_labels = None
depends_on = None

BINDING = (
    "(issuer_link_id IS NULL AND link_epoch IS NULL AND allowed_scopes_text IS NULL) OR "
    "(issuer_link_id IS NOT NULL AND length(issuer_link_id) BETWEEN 1 AND 128 "
    "AND link_epoch IS NOT NULL AND length(link_epoch) BETWEEN 1 AND 128 "
    "AND allowed_scopes_text IS NOT NULL)"
)
OLD_UNIQUE = "provider_connections_account_id_client_id_surface_key"
NAMING = {
    "uq": "%(table_name)s_%(column_0_name)s_%(column_1_name)s_%(column_2_name)s_key"
}


def upgrade():
    schema = context.config.attributes.get("shipagent_control_plane_schema")
    op.add_column("cloud_accounts", sa.Column("issuer", sa.String(2048)), schema=schema)
    with op.batch_alter_table(
        "provider_connections", schema=schema, naming_convention=NAMING
    ) as batch:
        batch.add_column(sa.Column("issuer_link_id", sa.String(128)))
        batch.add_column(sa.Column("link_epoch", sa.String(128)))
        batch.add_column(sa.Column("allowed_scopes_text", sa.Text()))
        batch.drop_constraint(OLD_UNIQUE, type_="unique")
        batch.create_check_constraint("ck_provider_connections_link_binding", BINDING)
    op.create_index(
        "uq_provider_connections_legacy",
        "provider_connections",
        ["account_id", "client_id", "surface"],
        unique=True,
        schema=schema,
        sqlite_where=sa.text("issuer_link_id IS NULL"),
        postgresql_where=sa.text("issuer_link_id IS NULL"),
    )
    op.create_index(
        "uq_provider_connections_strict_link",
        "provider_connections",
        ["account_id", "client_id", "surface", "issuer_link_id"],
        unique=True,
        schema=schema,
        sqlite_where=sa.text("issuer_link_id IS NOT NULL"),
        postgresql_where=sa.text("issuer_link_id IS NOT NULL"),
    )


def downgrade():
    schema = context.config.attributes.get("shipagent_control_plane_schema")
    prefix = '"' + schema.replace('"', '""') + '".' if schema else ""
    if op.get_context().dialect.name == "postgresql":
        # The no-bindings predicate and DDL share one transaction. Exclude
        # request writes before reading that predicate, in account→link order.
        op.execute(
            sa.text(f"LOCK TABLE {prefix}cloud_accounts IN ACCESS EXCLUSIVE MODE")
        )
        op.execute(
            sa.text(f"LOCK TABLE {prefix}provider_connections IN ACCESS EXCLUSIVE MODE")
        )
    elif not context.is_offline_mode():
        # SQLite migrations also reserve the writer before the precondition.
        op.execute(sa.text("UPDATE cloud_accounts SET issuer=issuer WHERE 0"))
    predicate = (
        f"EXISTS (SELECT 1 FROM {prefix}cloud_accounts WHERE issuer IS NOT NULL) OR "
        f"EXISTS (SELECT 1 FROM {prefix}provider_connections WHERE issuer_link_id IS NOT NULL)"
    )
    # Removing real strict bindings would erase tombstones/policy. Only the
    # lossless legacy-only rollback is supported; no silent merge or deletion.
    if context.is_offline_mode():
        op.execute(
            sa.text(
                "DO $$ BEGIN IF "
                + predicate
                + " THEN RAISE EXCEPTION 'strict provider links prevent downgrade'; END IF; END $$"
            )
        )
    elif op.get_bind().scalar(sa.text("SELECT " + predicate)):
        raise RuntimeError("strict provider links prevent downgrade")
    op.drop_index(
        "uq_provider_connections_strict_link",
        table_name="provider_connections",
        schema=schema,
    )
    op.drop_index(
        "uq_provider_connections_legacy",
        table_name="provider_connections",
        schema=schema,
    )
    with op.batch_alter_table(
        "provider_connections", schema=schema, naming_convention=NAMING
    ) as batch:
        batch.drop_constraint("ck_provider_connections_link_binding", type_="check")
        batch.drop_column("allowed_scopes_text")
        batch.drop_column("link_epoch")
        batch.drop_column("issuer_link_id")
        batch.create_unique_constraint(
            OLD_UNIQUE, ["account_id", "client_id", "surface"]
        )
    op.drop_column("cloud_accounts", "issuer", schema=schema)
