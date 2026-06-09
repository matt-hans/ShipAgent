from sqlalchemy import select

from src.control_plane.models import CloudAccount, ProviderConnection


async def test_auth0_subject_maps_to_one_cloud_account(control_db):
    account = CloudAccount(auth0_subject="auth0|owner-1")
    control_db.add(account)
    await control_db.commit()

    loaded = await control_db.scalar(
        select(CloudAccount).where(
            CloudAccount.auth0_subject == "auth0|owner-1"
        )
    )
    assert loaded.id == account.id


def test_provider_connection_never_owns_account_identity():
    columns = ProviderConnection.__table__.columns
    assert "account_id" in columns
    assert "provider_subject" not in columns

