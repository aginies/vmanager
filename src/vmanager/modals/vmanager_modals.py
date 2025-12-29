"""
Vmanager modals
"""
from textual.app import ComposeResult
from textual.message import Message
from textual.containers import Horizontal, Vertical
from textual.widgets import (
        Button, Input, Label,
        RadioButton, RadioSet
        )
from constants import VmStatus
from modals.base_modals import BaseModal


class FilterModal(BaseModal[None]):
    """Modal screen for selecting a filter."""

    class FilterChanged(Message):
        """Posted when the filter settings are applied."""
        def __init__(self, status: str, search: str) -> None:
            super().__init__()
            self.status = status
            self.search = search

    def __init__(self, current_search: str = "", current_status: str = VmStatus.DEFAULT) -> None:
        super().__init__()
        self.current_search = current_search
        self.current_status = current_status

    def compose(self) -> ComposeResult:
        with Vertical(id="filter-dialog"):
            yield Label("Filter by Name")
            with Vertical(classes="info-details"):
                yield Input(placeholder="Enter VM name...", id="search-input", value=self.current_search)
                with RadioSet(id="status-radioset"):
                    yield RadioButton("All", id=f"status_{VmStatus.DEFAULT}", value=self.current_status == VmStatus.DEFAULT)
                    yield RadioButton("Running", id=f"status_{VmStatus.RUNNING}", value=self.current_status == VmStatus.RUNNING)
                    yield RadioButton("Paused", id=f"status_{VmStatus.PAUSED}", value=self.current_status == VmStatus.PAUSED)
                    yield RadioButton("Stopped", id=f"status_{VmStatus.STOPPED}", value=self.current_status == VmStatus.STOPPED)
                    yield RadioButton("Manually Selected", id=f"status_{VmStatus.SELECTED}", value=self.current_status == VmStatus.SELECTED)
            with Horizontal():
                yield Button("Apply", id="apply-btn", variant="success")
                yield Button("Cancel", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.app.pop_screen()
        elif event.button.id == "apply-btn":
            search_text = self.query_one("#search-input", Input).value
            radioset = self.query_one(RadioSet)
            status_button = radioset.pressed_button
            status = VmStatus.DEFAULT
            if status_button:
                status = status_button.id.replace("status_", "")

            self.post_message(self.FilterChanged(status=status, search=search_text))
            self.app.pop_screen()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handles Enter key press in the search input."""
        # This implicitly acts as an "Apply" button press
        search_text = self.query_one("#search-input", Input).value
        radioset = self.query_one(RadioSet)
        status_button = radioset.pressed_button
        status = VmStatus.DEFAULT
        if status_button:
            status = status_button.id.replace("status_", "")

        self.post_message(self.FilterChanged(status=status, search=search_text))
        self.app.pop_screen()

class CreateVMModal(BaseModal[dict | None]):
    """Modal screen for creating a new VM."""

    def compose(self) -> ComposeResult:
        with Vertical(id="create-vm-dialog"):
            yield Label("Create New VM")
            yield Input(placeholder="VM Name", id="vm-name-input", value="new_vm")
            yield Input(placeholder="Memory (MB, e.g., 2048)", id="vm-memory-input", value="2048")
            yield Input(placeholder="VCPU (e.g., 2)", id="vm-vcpu-input", value="2")
            yield Input(placeholder="Disk Image Path (e.g., /var/lib/libvirt/images/myvm.qcow2)", id="vm-disk-input", value="/var/lib/libvirt/images/new_vm.qcow2")
            # For simplicity, we won't add network details yet.
            with Horizontal():
                yield Button("Create", variant="primary", id="create-btn", classes="Buttonpage")
                yield Button("Cancel", variant="default", id="cancel-btn", classes="Buttonpage")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create-btn":
            name = self.query_one("#vm-name-input", Input).value
            memory = self.query_one("#vm-memory-input", Input).value
            vcpu = self.query_one("#vm-vcpu-input", Input).value
            disk = self.query_one("#vm-disk-input", Input).value
            self.dismiss({'name': name, 'memory': memory, 'vcpu': vcpu, 'disk': disk})
        elif event.button.id == "cancel-btn":
            self.dismiss(None)
