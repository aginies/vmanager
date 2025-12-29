"""
Dialog box for VMcard
"""

from textual.app import ComposeResult
from textual.containers import ScrollableContainer, Horizontal, Vertical, Grid
from textual.widgets import (
        Button, Label, Checkbox, Select, Input, ListView, ListItem,
        Switch, Markdown,
        )
from modals.base_modals import BaseDialog
from config import load_config, save_config

class DeleteVMConfirmationDialog(BaseDialog[tuple[bool, bool]]):
    """A dialog to confirm VM deletion with an option to delete storage."""

    def __init__(self, vm_name: str) -> None:
        super().__init__()
        self.vm_name = vm_name

    def compose(self):
        yield Vertical(
            Markdown(f"Are you sure you want to delete VM '{self.vm_name}'?", id="question"),
            Checkbox("Delete storage volumes", id="delete-storage-checkbox", value=True),
            Label(""),
            Horizontal(
                Button("Yes", variant="error", id="yes", classes="dialog-buttons"),
                Button("No", variant="primary", id="no", classes="dialog-buttons"),
                id="dialog-buttons",
            ),
            id="delete-vm-dialog",
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

class AdvancedCloneDialog(BaseDialog[dict | None]):
    """A dialog to ask for a new VM name and number of clones."""

    def compose(self):
        yield Grid(
            Label("Enter base name for new VM(s)"),
            Input(placeholder="new_vm_base_name", id="base_name_input"),
            Label("Suffix for clone names (e.g., _C)"),
            Input(placeholder="e.g., -clone", id="clone_suffix_input"),
            Label("Number of clones to create"),
            Input(value="1", id="clone_count_input", type="integer"),
            Button("Clone", variant="success", id="clone_vm"),
            Button("Cancel", variant="error", id="cancel"),
            id="clone-dialog"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "clone_vm":
            base_name_input = self.query_one("#base_name_input", Input)
            clone_count_input = self.query_one("#clone_count_input", Input)
            clone_suffix_input = self.query_one("#clone_suffix_input", Input)

            base_name = base_name_input.value.strip()
            clone_count_str = clone_count_input.value.strip()
            clone_suffix = clone_suffix_input.value.strip()

            if not base_name:
                self.app.show_error_message("Base name cannot be empty.")
                return

            try:
                clone_count = int(clone_count_str)
                if clone_count < 1:
                    raise ValueError()
            except ValueError:
                self.app.show_error_message("Number of clones must be a positive integer.")
                return

            if clone_count > 1 and not clone_suffix:
                self.app.show_error_message("Suffix is mandatory when creating multiple clones.")
                return

            self.dismiss({"base_name": base_name, "count": clone_count, "suffix": clone_suffix})
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

class WebConsoleDialog(BaseDialog[str | None]):
    """A dialog to show the web console URL."""

    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url

    def compose(self):
        yield Vertical(
            Markdown("**Web Console** is running at: (ctrl+click to open)"),
            Markdown(self.url),
            #Link("Open Link To a Browser", url=self.url),
            Label(""),
            Horizontal(
                Button("Stop Web Console service", variant="error", id="stop"),
                Button("Close this Window", variant="primary", id="close"),
                id="dialog-buttons",
            ),
            id="webconsole-dialog",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "stop":
            self.dismiss("stop")
        else:
            self.dismiss(None)

class WebConsoleConfigDialog(BaseDialog[bool]):
    """A dialog to configure and start the web console."""

    def __init__(self, is_remote: bool) -> None:
        super().__init__()
        self.is_remote = is_remote
        self.config = load_config()
        self.text_remote = "Run Web console on remote server. This will use a **LOT** of network bandwidth. It is recommended to **reduce quality** and enable **max compression**."

    def compose(self) -> ComposeResult:
        with ScrollableContainer(id="webconsole-config-dialog"):
            yield Label("Web Console Configuration", id="webconsole-config-title")

            if self.is_remote:
                remote_console_enabled = self.config.get('REMOTE_WEBCONSOLE', False)
                label_text = self.text_remote if remote_console_enabled else "Run Web console on local machine"
                yield Markdown(label_text, id="console-location-label")
                yield Switch(value=remote_console_enabled, id="remote-console-switch")

                with Vertical(id="remote-options") as remote_opts:
                    remote_opts.display = remote_console_enabled

                    quality_options = [(str(i), i) for i in range(10)]
                    compression_options = [(str(i), i) for i in range(10)]

                    yield Label("VNC Quality (0=low, 9=high)")
                    yield Select(quality_options, value=self.config.get('VNC_QUALITY', 0), id="quality-select")

                    yield Label("VNC Compression (0=none, 9=max)")
                    yield Select(compression_options, value=self.config.get('VNC_COMPRESSION', 9), id="compression-select")
            else:
                yield Markdown("Web console will run locally.")

            yield Button("Start Web Console", variant="primary", id="start")
            yield Button("Cancel", variant="default", id="cancel")

    def on_switch_changed(self, event: Switch.Changed) -> None:
        if event.control.id == "remote-console-switch":
            markdown = self.query_one("#console-location-label", Markdown)
            remote_opts = self.query_one("#remote-options")
            if event.value:
                markdown.update(self.text_remote)
                remote_opts.display = True
            else:
                markdown.update("Run Web console on local machine")
                remote_opts.display = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start":
            config_changed = False
            if self.is_remote:
                remote_switch = self.query_one("#remote-console-switch", Switch)
                new_remote_value = remote_switch.value
                if self.config.get('REMOTE_WEBCONSOLE') != new_remote_value:
                    self.config['REMOTE_WEBCONSOLE'] = new_remote_value
                    config_changed = True

                if new_remote_value:
                    quality_select = self.query_one("#quality-select", Select)
                    new_quality_value = quality_select.value
                    if new_quality_value is not Select.BLANK and self.config.get('VNC_QUALITY') != new_quality_value:
                        self.config['VNC_QUALITY'] = new_quality_value
                        config_changed = True

                    compression_select = self.query_one("#compression-select", Select)
                    new_compression_value = compression_select.value
                    if new_compression_value is not Select.BLANK and self.config.get('VNC_COMPRESSION') != new_compression_value:
                        self.config['VNC_COMPRESSION'] = new_compression_value
                        config_changed = True
            else:
                # Not remote, so webconsole must be local
                if self.config.get('REMOTE_WEBCONSOLE') is not False:
                    self.config['REMOTE_WEBCONSOLE'] = False
                    config_changed = True

            if config_changed:
                save_config(self.config)
            self.dismiss(True)
        elif event.button.id == "cancel":
            self.dismiss(False)
