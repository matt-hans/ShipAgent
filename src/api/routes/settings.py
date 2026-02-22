"""API routes for application settings management.

Provides GET/PATCH for the settings singleton and credential status checks.
All endpoints use /api/v1/settings prefix.
"""

import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.db.connection import get_db
from src.services.settings_service import SettingsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsResponse(BaseModel):
    """Response schema for app settings."""
    agent_model: str | None = None
    batch_concurrency: int = 5
    shipper_name: str | None = None
    shipper_attention_name: str | None = None
    shipper_address1: str | None = None
    shipper_address2: str | None = None
    shipper_city: str | None = None
    shipper_state: str | None = None
    shipper_zip: str | None = None
    shipper_country: str | None = None
    shipper_phone: str | None = None
    ups_account_number: str | None = None
    ups_environment: str | None = None
    onboarding_completed: bool = False

    model_config = {"from_attributes": True}


class SettingsPatch(BaseModel):
    """Request schema for updating settings (all fields optional)."""
    agent_model: str | None = None
    batch_concurrency: int | None = None
    shipper_name: str | None = None
    shipper_attention_name: str | None = None
    shipper_address1: str | None = None
    shipper_address2: str | None = None
    shipper_city: str | None = None
    shipper_state: str | None = None
    shipper_zip: str | None = None
    shipper_country: str | None = None
    shipper_phone: str | None = None
    ups_account_number: str | None = None
    ups_environment: str | None = None


class CredentialStatusResponse(BaseModel):
    """Which credentials are configured (never returns values)."""
    anthropic_api_key: bool = False
    ups_client_id: bool = False
    ups_client_secret: bool = False
    shopify_access_token: bool = False
    filter_token_secret: bool = False


def _get_service(db: Session = Depends(get_db)) -> SettingsService:
    """Dependency injector for SettingsService."""
    return SettingsService(db)


@router.get("", response_model=SettingsResponse)
def get_settings(
    service: SettingsService = Depends(_get_service),
) -> SettingsResponse:
    """Get all application settings."""
    settings = service.get_or_create()
    return SettingsResponse.model_validate(settings)


@router.patch("", response_model=SettingsResponse)
def update_settings(
    data: SettingsPatch,
    service: SettingsService = Depends(_get_service),
    db: Session = Depends(get_db),
) -> SettingsResponse:
    """Update application settings (patch semantics)."""
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    try:
        settings = service.update(updates)
        db.commit()
        return SettingsResponse.model_validate(settings)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


class SetCredentialRequest(BaseModel):
    """Request to set a credential in the secure store."""
    key: str
    value: str


@router.get("/credentials/status", response_model=CredentialStatusResponse)
def get_credential_status() -> CredentialStatusResponse:
    """Check which credentials are configured (never returns values).

    Checks keyring first (production), then env vars (dev fallback).
    """
    from src.services.keyring_store import KeyringStore
    store = KeyringStore()

    def _is_set(key: str) -> bool:
        return store.has(key) or bool(os.environ.get(key, "").strip())

    return CredentialStatusResponse(
        anthropic_api_key=_is_set("ANTHROPIC_API_KEY"),
        ups_client_id=_is_set("UPS_CLIENT_ID"),
        ups_client_secret=_is_set("UPS_CLIENT_SECRET"),
        shopify_access_token=_is_set("SHOPIFY_ACCESS_TOKEN"),
        filter_token_secret=_is_set("FILTER_TOKEN_SECRET"),
    )


@router.post("/credentials")
def set_credential(data: SetCredentialRequest) -> dict:
    """Set a credential in the secure store (keychain)."""
    from src.services.keyring_store import KeyringStore, MANAGED_CREDENTIALS
    if data.key not in MANAGED_CREDENTIALS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown credential: {data.key}. Valid: {MANAGED_CREDENTIALS}"
        )
    store = KeyringStore()
    store.set(data.key, data.value)
    return {"status": "stored", "key": data.key}


@router.post("/onboarding/complete")
def complete_onboarding(
    service: SettingsService = Depends(_get_service),
    db: Session = Depends(get_db),
) -> dict:
    """Mark onboarding as completed."""
    service.complete_onboarding()
    db.commit()
    return {"status": "completed"}
