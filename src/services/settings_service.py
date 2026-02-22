"""Service for application settings management.

Provides singleton access to AppSettings with patch-style updates.
"""

import logging
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import AppSettings, utc_now_iso

logger = logging.getLogger(__name__)

# Fields that can be updated via PATCH /settings.
# onboarding_completed is intentionally excluded — it can only be set
# via the dedicated complete_onboarding() method / POST endpoint.
_MUTABLE_FIELDS = {
    "agent_model", "batch_concurrency",
    "shipper_name", "shipper_attention_name",
    "shipper_address1", "shipper_address2",
    "shipper_city", "shipper_state", "shipper_zip",
    "shipper_country", "shipper_phone",
    "ups_account_number", "ups_environment",
}


class SettingsService:
    """CRUD service for the AppSettings singleton."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_or_create(self) -> AppSettings:
        """Return the settings singleton, creating it if absent."""
        settings = self._db.get(AppSettings, AppSettings.SINGLETON_ID)
        if settings is None:
            settings = AppSettings(id=AppSettings.SINGLETON_ID)
            self._db.add(settings)
            self._db.flush()
            logger.info("Created AppSettings singleton")
        return settings

    def update(self, patch: dict[str, Any]) -> AppSettings:
        """Apply patch-style updates to settings.

        Args:
            patch: Dict of field names to new values. Unknown fields raise ValueError.

        Returns:
            Updated AppSettings instance.

        Raises:
            ValueError: If patch contains unknown field names.
        """
        unknown = set(patch.keys()) - _MUTABLE_FIELDS
        if unknown:
            raise ValueError(f"Unknown setting fields: {unknown}")

        settings = self.get_or_create()
        for key, value in patch.items():
            setattr(settings, key, value)
        settings.updated_at = utc_now_iso()
        self._db.flush()
        return settings

    def complete_onboarding(self) -> AppSettings:
        """Mark onboarding as completed.

        Uses direct attribute set rather than update() because
        onboarding_completed is intentionally excluded from _MUTABLE_FIELDS
        to prevent toggling via PATCH /settings.
        """
        settings = self.get_or_create()
        settings.onboarding_completed = True
        settings.updated_at = utc_now_iso()
        self._db.flush()
        return settings
