"""
Modal for bulk VM operations
"""
from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal, ScrollableContainer
from textual.widgets import Label, Button, Markdown, Static, RadioSet, RadioButton

from modals.base_modals import BaseModal

class BulkActionModal(BaseModal[None]):
    """Modal screen for performing bulk actions on selected VMs."""

    def __init__(self, vm_names: list[str]) -> None:
        super().__init__()
        self.vm_names = vm_names

    def compose(self) -> ComposeResult:
        with Vertical(id="bulk-action-dialog"):
            yield Label("Selected VMs for Bulk Action")
            yield Static(classes="button-separator")
            with ScrollableContainer():
                all_vms = ", ".join(self.vm_names)
                yield Markdown(all_vms, id="selected-vms-list")

            yield Label("Choose Action:")
            with RadioSet(id="bulk-action-radioset"):
                yield RadioButton("Start VMs", id="action_start")
                yield RadioButton("Stop VMs (Graceful Shutdown)", id="action_stop")
                yield RadioButton("Force Off VMs", id="action_force_off")
                yield RadioButton("Pause VMs", id="action_pause")
                yield RadioButton("Delete VMs", id="action_delete")

            with Horizontal():
                yield Button("Execute", variant="primary", id="execute-action-btn", classes="button-container")
                yield Button("Cancel", variant="default", id="cancel-btn", classes="button-container")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "execute-action-btn":
            radioset = self.query_one(RadioSet)
            selected_action_button = radioset.pressed_button
            if selected_action_button:
                action = selected_action_button.id.replace("action_", "")
                self.dismiss({'action': action})
            else:
                self.app.show_error_message("Please select an action.")
        elif event.button.id == "cancel-btn":
            self.dismiss(None)
