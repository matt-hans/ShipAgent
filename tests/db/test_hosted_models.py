import pytest
from sqlalchemy import create_engine, delete, event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.db.models import (
    Base,
    ConfirmationRecord,
    ConnectedAccount,
    HostedTenant,
    UploadedArtifact,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def count_rows(db_session, model):
    return db_session.scalar(select(func.count()).select_from(model))


def test_hosted_tenant_defaults():
    tenant = HostedTenant(provider_host="openai", provider_subject="user-1")

    assert tenant.provider_host == "openai"
    assert tenant.provider_subject == "user-1"


def test_connected_account_scopes_round_trip():
    account = ConnectedAccount(
        tenant_id="tenant-1",
        provider="ups",
        account_key="ups:test",
        scopes_json='["shipments:create"]',
        status="connected",
    )

    assert "shipments:create" in account.scopes_json


def test_confirmation_record_tracks_one_time_use():
    record = ConfirmationRecord(
        tenant_id="tenant-1",
        operation="create_shipments",
        preview_id="preview-1",
        idempotency_key="idem-1",
        expires_at="2026-06-02T00:00:00Z",
    )

    assert record.used_at is None


def test_uploaded_artifact_has_tenant_scope():
    artifact = UploadedArtifact(
        tenant_id="tenant-1",
        artifact_type="orders",
        storage_key="tenant-1/uploads/orders.csv",
    )

    assert artifact.tenant_id == "tenant-1"


def test_hosted_tenant_commits_child_records_via_relationships(db_session):
    tenant = HostedTenant(
        provider_host="openai",
        provider_subject="user-with-children",
        connected_accounts=[
            ConnectedAccount(provider="ups", account_key="ups:test"),
        ],
        uploaded_artifacts=[
            UploadedArtifact(
                artifact_type="orders",
                storage_key="tenant-1/uploads/orders.csv",
            ),
        ],
        confirmation_records=[
            ConfirmationRecord(
                operation="create_shipments",
                preview_id="preview-1",
                idempotency_key="idem-1",
                expires_at="2026-06-02T00:00:00Z",
            ),
        ],
    )

    db_session.add(tenant)
    db_session.commit()

    assert tenant.id is not None
    assert tenant.connected_accounts[0].tenant_id == tenant.id
    assert tenant.uploaded_artifacts[0].tenant_id == tenant.id
    assert tenant.confirmation_records[0].tenant_id == tenant.id


def test_deleting_hosted_tenant_cascades_child_records(db_session):
    tenant = HostedTenant(
        provider_host="openai",
        provider_subject="user-delete",
        connected_accounts=[
            ConnectedAccount(provider="ups", account_key="ups:test"),
        ],
        uploaded_artifacts=[
            UploadedArtifact(
                artifact_type="orders",
                storage_key="tenant-1/uploads/orders.csv",
            ),
        ],
        confirmation_records=[
            ConfirmationRecord(
                operation="create_shipments",
                preview_id="preview-1",
                idempotency_key="idem-1",
                expires_at="2026-06-02T00:00:00Z",
            ),
        ],
    )
    db_session.add(tenant)
    db_session.commit()
    tenant_id = tenant.id

    db_session.execute(delete(HostedTenant).where(HostedTenant.id == tenant_id))
    db_session.commit()

    assert count_rows(db_session, HostedTenant) == 0
    assert count_rows(db_session, ConnectedAccount) == 0
    assert count_rows(db_session, UploadedArtifact) == 0
    assert count_rows(db_session, ConfirmationRecord) == 0


def test_connected_account_server_defaults_work_on_db_insert(db_session):
    tenant = HostedTenant(provider_host="openai", provider_subject="user-defaults")
    db_session.add(tenant)
    db_session.commit()

    db_session.execute(
        text(
            """
            INSERT INTO connected_accounts (
                id,
                tenant_id,
                provider,
                account_key,
                created_at,
                updated_at
            )
            VALUES (
                :id,
                :tenant_id,
                :provider,
                :account_key,
                :created_at,
                :updated_at
            )
            """
        ),
        {
            "id": "account-defaults",
            "tenant_id": tenant.id,
            "provider": "ups",
            "account_key": "ups:test",
            "created_at": "2026-06-02T00:00:00Z",
            "updated_at": "2026-06-02T00:00:00Z",
        },
    )
    db_session.commit()

    account = db_session.get(ConnectedAccount, "account-defaults")

    assert account.scopes_json == "[]"
    assert account.status == "pending"


def test_hosted_tenant_provider_subject_is_unique(db_session):
    db_session.add_all(
        [
            HostedTenant(provider_host="openai", provider_subject="user-1"),
            HostedTenant(provider_host="openai", provider_subject="user-1"),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_confirmation_idempotency_key_is_unique_per_tenant(db_session):
    tenant = HostedTenant(provider_host="openai", provider_subject="user-confirm")
    db_session.add(tenant)
    db_session.commit()

    db_session.add_all(
        [
            ConfirmationRecord(
                tenant_id=tenant.id,
                operation="create_shipments",
                preview_id="preview-1",
                idempotency_key="idem-1",
                expires_at="2026-06-02T00:00:00Z",
            ),
            ConfirmationRecord(
                tenant_id=tenant.id,
                operation="create_shipments",
                preview_id="preview-2",
                idempotency_key="idem-1",
                expires_at="2026-06-02T00:00:00Z",
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_hosted_child_foreign_keys_delete_cascade_in_metadata():
    for model in (ConnectedAccount, UploadedArtifact, ConfirmationRecord):
        foreign_key = next(iter(model.__table__.c.tenant_id.foreign_keys))

        assert foreign_key.ondelete == "CASCADE"
