"""
Base Modal stuff
"""
from typing import TypeVar
import re
from textual.screen import ModalScreen, Screen

T = TypeVar("T")

class BaseModal(ModalScreen[T]):
    BINDINGS = [("escape", "cancel_modal", "Cancel")]

    def action_cancel_modal(self) -> None:
        self.dismiss(None)

class BaseDialog(Screen[T]):
    """A base class for dialogs with a cancel binding."""

    BINDINGS = [("escape", "cancel_modal", "Cancel")]

    def action_cancel_modal(self) -> None:
        """Cancel the modal dialog."""
        self.dismiss(None)

    @staticmethod
    def validate_name(name: str) -> str | None:
        """
        Validates a name to be alphanumeric with underscores, not hyphens.
        Returns an error message string if invalid, otherwise None.
        """
        if not name:
            return "Name cannot be empty."
        if not re.fullmatch(r"^[a-zA-Z0-9_]+$", name):
            return "Name must be alphanumeric and can contain underscores, but not hyphens."
        return None
