"""
Dialog box for VMcard
"""

from textual.containers import Horizontal, Vertical
from textual.widgets import (
        Button, Label, Checkbox, Select, Input, Link, ListView, ListItem
        )
from modals.base_modals import BaseDialog

class DeleteVMConfirmationDialog(BaseDialog[tuple[bool, bool]]):
    """A dialog to confirm VM deletion with an option to delete storage."""

    def __init__(self, vm_name: str) -> None:
        super().__init__()
        self.vm_name = vm_name

    def compose(self):
        yield Vertical(
            Label(f"Are you sure you want to delete VM '{self.vm_name}'?", id="question"),
            Checkbox("Delete storage volumes", id="delete-storage-checkbox"),
            Horizontal(
                Button("Yes", variant="error", id="yes", classes="dialog-buttons"),
                Button("No", variant="primary", id="no", classes="dialog-buttons"),
                id="dialog-buttons",
            ),
            id="dialog",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "yes":
            delete_storage = self.query_one("#delete-storage-checkbox", Checkbox).value
            self.dismiss((True, delete_storage))
        else:
            self.dismiss((False, False))

    def action_cancel_modal(self) -> None:
        """Cancel the modal."""
        self.dismiss((False, False))

class ChangeNetworkDialog(BaseDialog[dict | None]):
    """A dialog to change a VM's network interface."""

    def __init__(self, interfaces: list[dict], networks: list[str]) -> None:
        super().__init__()
        self.interfaces = interfaces
        self.networks = networks

    def compose(self):
        interface_options = [(f"{iface['mac']} ({iface['network']})", iface['mac']) for iface in self.interfaces]
        network_options = [(str(net), str(net)) for net in self.networks]

        with Vertical(id="dialog"):
            yield Label("Select interface and new network")
            yield Select(interface_options, id="interface-select")
            yield Select(network_options, id="network-select")
            with Horizontal(id="dialog-buttons"):
                yield Button("Change", variant="success", id="change")
                yield Button("Cancel", variant="error", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "change":
            interface_select = self.query_one("#interface-select", Select)
            network_select = self.query_one("#network-select", Select)

            mac_address = interface_select.value
            new_network = network_select.value

            if mac_address is Select.BLANK or new_network is Select.BLANK:
                self.app.show_error_message("Please select an interface and a network.")
                return

            self.dismiss({"mac_address": mac_address, "new_network": new_network})
        else:
            self.dismiss(None)

class WebConsoleDialog(BaseDialog[str | None]):
    """A dialog to show the web console URL."""

    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url

    def compose(self):
        yield Vertical(
            Label("Web Console is running at"),
            Input(value=self.url, disabled=True),
            Link("Open Link To a Browser", url=self.url),
            Label(""),
            Horizontal(
                Button("Stop Web Console service", variant="error", id="stop"),
                Button("Close this Window", variant="primary", id="close"),
                id="dialog-buttons",
            ),
            id="dialog",
            classes="info-container",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "stop":
            self.dismiss("stop")
        else:
            self.dismiss(None)

class CloneNameDialog(BaseDialog[str | None]):
    """A dialog to ask for a new VM name when cloning."""

    def compose(self):
        yield Vertical(
            Label("Enter new VM name", id="question"),
            Input(placeholder="new_vm_name"),
            Horizontal(
                Button("Clone", variant="success", id="clone_vm"),
                Button("Cancel", variant="error", id="cancel"),
                id="dialog-buttons",
            ),
            id="dialog",
            classes="info-container",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "clone_vm":
            input_widget = self.query_one(Input)
            new_name = input_widget.value.strip()

            error = self.validate_name(new_name)
            if error:
                self.app.show_error_message(error)
                return

            self.dismiss(new_name)
        else:
            self.dismiss(None)

class RenameVMDialog(BaseDialog[str | None]):
    """A dialog to ask for a new VM name when renaming."""

    def __init__(self, current_name: str) -> None:
        super().__init__()
        self.current_name = current_name

    def compose(self):
        yield Vertical(
            Label(f"Current name: {self.current_name}"),
            Label("Enter new VM name", id="question"),
            Input(placeholder="new_vm_name"),
            Horizontal(
                Button("Rename", variant="success", id="rename_vm"),
                Button("Cancel", variant="error", id="cancel"),
                id="dialog-buttons",
            ),
            id="dialog",
            classes="info-container",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "rename_vm":
            input_widget = self.query_one(Input)
            new_name = input_widget.value.strip()

            error = self.validate_name(new_name)
            if error:
                self.app.show_error_message(error)
                return

            self.dismiss(new_name)
        else:
            self.dismiss(None)

class SelectSnapshotDialog(BaseDialog[str | None]):
    """A dialog to select a snapshot from a list."""

    def __init__(self, snapshots: list, prompt: str) -> None:
        super().__init__()
        self.snapshots = snapshots
        self.prompt = prompt

    def compose(self):
        yield Vertical(
            Label(self.prompt),
            ListView(
                *[ListItem(Label(snap.getName())) for snap in self.snapshots],
                id="snapshot-list",
            ),
            Button("Cancel", variant="error", id="cancel"),
            id="dialog",
        )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        snapshot_name = event.item.query_one(Label).renderable
        self.dismiss(str(snapshot_name))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)

class SnapshotNameDialog(BaseDialog[str | None]):
    """A dialog to ask for a snapshot name."""

    def compose(self):
        yield Vertical(
            Label("Enter snapshot name", id="question"),
            Input(placeholder="snapshot_name"),
            Horizontal(
                Button("Create", variant="success", id="create"),
                Button("Cancel", variant="error", id="cancel"),
                id="dialog-buttons",
            ),
            id="dialog",
            classes="info-container",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create":
            input_widget = self.query_one(Input)
            snapshot_name = input_widget.value.strip()

            error = self.validate_name(snapshot_name)
            if error:
                self.app.show_error_message(error)
                return

            self.dismiss(snapshot_name)
        else:
            self.dismiss(None)
