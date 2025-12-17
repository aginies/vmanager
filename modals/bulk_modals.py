"""
Modal for bulk VM operations
"""
from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal, ScrollableContainer
from textual.widgets import Label, Button, ListItem, ListView

from modals.base_modals import BaseModal

class BulkActionModal(BaseModal[None]):
    """Modal screen for performing bulk actions on selected VMs."""

    def __init__(self, vm_names: list[str]) -> None:
        super().__init__()
        self.vm_names = vm_names

    def compose(self) -> ComposeResult:
        with Vertical(id="bulk-action-dialog"):
            yield Label("Selected VMs for Bulk Action:")
            with ScrollableContainer():
                yield ListView(
                    *[ListItem(Label(name)) for name in self.vm_names],
                    id="selected-vms-list"
                )
            with Horizontal():
                yield Button("Perform Action", variant="primary", id="perform-action-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "perform-action-btn":
            # For now, we'll just dismiss the modal... lot of work to do...
            self.dismiss(None)
        elif event.button.id == "cancel-btn":
            self.dismiss(None)
