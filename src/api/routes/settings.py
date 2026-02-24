"""API routes for application settings management.

Provides GET/PATCH for the settings singleton and credential status checks.
All endpoints use /api/v1/settings prefix.
"""

import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
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
    """Request schema for updating settings (true PATCH semantics).

    Uses Pydantic's model_fields_set to distinguish omitted fields from
    fields explicitly set to null. Only fields present in the JSON body
    appear in get_updates().
    """
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

    @field_validator("batch_concurrency", mode="before")
    @classmethod
    def validate_batch_concurrency(cls, v: Any) -> Any:
        """Ensure batch_concurrency is in [1, 20] when provided."""
        if v is None:
            return v
        if not isinstance(v, int):
            raise ValueError("batch_concurrency must be an integer")
        if v < 1 or v > 20:
            raise ValueError("batch_concurrency must be between 1 and 20")
        return v

    @field_validator("ups_environment", mode="before")
    @classmethod
    def validate_ups_environment(cls, v: Any) -> Any:
        """Ensure ups_environment is 'test' or 'production' when provided."""
        if v is None:
            return v
        if v not in ("test", "production"):
            raise ValueError("ups_environment must be 'test' or 'production'")
        return v

    @field_validator("shipper_country", mode="before")
    @classmethod
    def validate_shipper_country(cls, v: Any) -> Any:
        """Ensure shipper_country is a 2-letter code when provided."""
        if v is None:
            return v
        if not isinstance(v, str) or len(v) != 2:
            raise ValueError("shipper_country must be a 2-letter ISO code")
        return v.upper()

    def get_updates(self) -> dict[str, Any]:
        """Return only fields that were explicitly set in the request."""
        return {
            k: getattr(self, k) for k in self.model_fields_set
        }


class CredentialStatusResponse(BaseModel):
    """Which credentials are configured (never returns values)."""
    anthropic_api_key: bool = False
    ups_client_id: bool = False
    ups_client_secret: bool = False
    shopify_access_token: bool = False
    filter_token_secret: bool = False
    shipagent_api_key: bool = False


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
    """Update application settings (true PATCH semantics).

    Omitted fields are unchanged. Fields set to null are cleared.
    """
    updates = data.get_updates()
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
    value: str = Field(min_length=1)


@router.get("/credentials/status", response_model=CredentialStatusResponse)
def get_credential_status() -> CredentialStatusResponse:
    """Check which credentials are configured (never returns values).

    Uses get_all_status() for a single-pass check across keyring + env.
    """
    from src.services.keyring_store import KeyringStore
    store = KeyringStore()
    status = store.get_all_status()

    return CredentialStatusResponse(
        anthropic_api_key=status.get("ANTHROPIC_API_KEY", False),
        ups_client_id=status.get("UPS_CLIENT_ID", False),
        ups_client_secret=status.get("UPS_CLIENT_SECRET", False),
        shopify_access_token=status.get("SHOPIFY_ACCESS_TOKEN", False),
        filter_token_secret=status.get("FILTER_TOKEN_SECRET", False),
        shipagent_api_key=status.get("SHIPAGENT_API_KEY", False),
    )


@router.post("/credentials")
def set_credential(data: SetCredentialRequest) -> dict:
    """Set a credential in the secure store (keychain).

    Returns 503 with actionable message if the keychain is unavailable,
    so the onboarding UI can display a helpful error instead of a raw 500.
    """
    from src.services.keyring_store import KeyringStore, MANAGED_CREDENTIALS
    if data.key not in MANAGED_CREDENTIALS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown credential: {data.key}. Valid: {MANAGED_CREDENTIALS}"
        )
    store = KeyringStore()
    try:
        store.set(data.key, data.value)
    except Exception as exc:
        logger.error("Failed to store credential %s: %s", data.key, exc)
        raise HTTPException(
            status_code=503,
            detail=(
                f"Could not save {data.key} to system keychain. "
                "The keychain may be locked or unavailable. "
                "Try unlocking your keychain and retry."
            ),
        ) from None
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
