"""Service for custom /command CRUD operations.

Manages user-defined slash commands that expand to shipping instructions.
Commands are stored without the '/' prefix; resolution happens on the frontend.

Example:
    svc = CustomCommandService(db)
    cmd = svc.create_command(name="daily-restock", body="Ship 3 boxes to @nyc")
"""

import logging
import re

from sqlalchemy.orm import Session

from src.db.models import CustomCommand, utc_now_iso

logger = logging.getLogger(__name__)

COMMAND_NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class CustomCommandService:
    """CRUD operations for custom slash commands.

    Methods do NOT call db.commit() — the caller is responsible for committing.
    """

    def __init__(self, db: Session) -> None:
        """Initialize with a SQLAlchemy session.

        Args:
            db: Active database session.
        """
        self.db = db

    def create_command(
        self,
        name: str,
        body: str,
        description: str | None = None,
    ) -> CustomCommand:
        """Create a new custom command.

        Args:
            name: Command slug without '/' prefix.
            body: Full instruction text.
            description: Optional human note.

        Returns:
            The created CustomCommand record.

        Raises:
            ValueError: If name is invalid or already exists.
        """
        clean_name = name.lstrip("/").lower().strip()
        if not COMMAND_NAME_PATTERN.match(clean_name):
            raise ValueError(
                f"Invalid command name: '{clean_name}'. "
                "Must be lowercase alphanumeric with hyphens."
            )

        existing = self.get_by_name(clean_name)
        if existing:
            raise ValueError(f"Command '/{clean_name}' already exists.")

        cmd = CustomCommand(
            name=clean_name,
            body=body,
            description=description,
        )
        self.db.add(cmd)
        self.db.flush()
        logger.info("Created command /%s", clean_name)
        return cmd

    def get_by_name(self, name: str) -> CustomCommand | None:
        """Find a command by name.

        Args:
            name: Command name with or without '/' prefix.

        Returns:
            CustomCommand if found, None otherwise.
        """
        clean = name.lstrip("/").lower().strip()
        return (
            self.db.query(CustomCommand)
            .filter(CustomCommand.name == clean)
            .first()
        )

    def list_commands(self) -> list[CustomCommand]:
        """List all custom commands ordered by name.

        Returns:
            All custom commands.
        """
        return (
            self.db.query(CustomCommand)
            .order_by(CustomCommand.name)
            .all()
        )

    def update_command(self, command_id: str, **kwargs) -> CustomCommand:
        """Partially update a command by ID.

        Args:
            command_id: UUID of the command.
            **kwargs: Fields to update.

        Returns:
            The updated CustomCommand.

        Raises:
            ValueError: If command not found or name validation fails.
        """
        cmd = self.db.query(CustomCommand).filter(CustomCommand.id == command_id).first()
        if not cmd:
            raise ValueError(f"Command {command_id} not found.")

        if "name" in kwargs and kwargs["name"] is not None:
            new_name = kwargs["name"].lstrip("/").lower().strip()
            if not COMMAND_NAME_PATTERN.match(new_name):
                raise ValueError(f"Invalid command name: '{new_name}'.")
            if new_name != cmd.name:
                existing = self.get_by_name(new_name)
                if existing:
                    raise ValueError(f"Command '/{new_name}' already in use.")
            kwargs["name"] = new_name

        for key, value in kwargs.items():
            if value is not None and hasattr(cmd, key):
                setattr(cmd, key, value)

        cmd.updated_at = utc_now_iso()
        self.db.flush()
        logger.info("Updated command /%s", cmd.name)
        return cmd

    def delete_command(self, command_id: str) -> bool:
        """Delete a command by ID.

        Args:
            command_id: UUID of the command.

        Returns:
            True if deleted, False if not found.
        """
        cmd = self.db.query(CustomCommand).filter(CustomCommand.id == command_id).first()
        if not cmd:
            return False
        name = cmd.name
        self.db.delete(cmd)
        self.db.flush()
        logger.info("Deleted command /%s", name)
        return True
