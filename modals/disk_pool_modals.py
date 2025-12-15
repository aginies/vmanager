"""
Storage Pool Volume 
"""
import os
import libvirt
from textual.containers import ScrollableContainer, Horizontal, Vertical
from textual.widgets import (
        Label, ListView, ListItem, Button, Checkbox, Input,
        Select,
        )
from textual.app import ComposeResult
from textual import on
from storage_manager import create_storage_pool
from modals.base_modals import BaseModal
from modals.utils_modals import DirectorySelectionModal

class SelectPoolModal(BaseModal[str | None]):
    """Modal screen for selecting a storage pool from a list."""

    def __init__(self, pools: list[str], prompt: str) -> None:
        super().__init__()
        self.pools = pools
        self.prompt = prompt
        self.selected_pool = None

    def compose(self) -> ComposeResult:
        with Vertical(id="select-pool-dialog", classes="select-pool-dialog"):
            yield Label(self.prompt)
            with ScrollableContainer():
                yield ListView(
                    *[ListItem(Label(pool)) for pool in self.pools],
                    id="pool-selection-list"
                )
            yield Button("Cancel", variant="error", id="cancel")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.selected_pool = str(event.item.query_one(Label).renderable)
        self.dismiss(self.selected_pool)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)


class SelectDiskModal(BaseModal[str | None]):
    """Modal screen for selecting a disk from a list."""

    def __init__(self, disks: list[str], prompt: str) -> None:
        super().__init__()
        self.disks = disks
        self.prompt = prompt
        self.selected_disk = None

    def compose(self) -> ComposeResult:
        with Vertical(id="select-disk-dialog", classes="select-disk-dialog"):
            yield Label(self.prompt)
            with ScrollableContainer():
                yield ListView(
                    *[ListItem(Label(disk)) for disk in self.disks],
                    id="disk-selection-list"
                )
            yield Button("Cancel", variant="error", id="cancel")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.selected_disk = str(event.item.query_one(Label).renderable)
        self.dismiss(self.selected_disk)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)

class RemoveDiskModal(BaseModal[str | None]):
    """Modal screen for removing a disk."""

    def __init__(self, disks: list) -> None:
        super().__init__()
        self.disks = disks

    def compose(self) -> ComposeResult:
        with Vertical(id="remove-disk-dialog"):
            yield Label("Select Disk to Remove")
            yield ListView(
                *[ListItem(Label(disk)) for disk in self.disks],
                id="remove-disk-list"
            )
            with Horizontal():
                yield Button("Remove", variant="error", id="remove-btn", classes="Buttonpage delete-button")
                yield Button("Cancel", variant="default", id="cancel-btn", classes="Buttonpage")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.selected_disk = event.item.query_one(Label).renderable

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "remove-btn" and hasattr(self, "selected_disk"):
            self.dismiss(self.selected_disk)
        elif event.button.id == "cancel-btn":
            self.dismiss(None)

class AddDiskModal(BaseModal[dict | None]):
    """Modal screen for adding a new disk."""

    def compose(self) -> ComposeResult:
        with Vertical(id="add-disk-dialog"):
            yield Label("Add New Disk")
            yield Input(placeholder="Path to disk image or ISO", id="disk-path-input")
            yield Checkbox("Create new disk image", id="create-disk-checkbox")
            yield Input(placeholder="Size in GB (e.g., 10)", id="disk-size-input", disabled=True)
            yield Select([("qcow2", "qcow2"), ("raw", "raw")], id="disk-format-select", disabled=True, value="qcow2", classes="disk-format-select")
            yield Checkbox("CD-ROM", id="cdrom-checkbox")
            with Horizontal():
                yield Button("Add", variant="primary", id="add-btn", classes="Buttonpage")
                yield Button("Cancel", variant="default", id="cancel-btn", classes="Buttonpage")

    @on(Checkbox.Changed, "#create-disk-checkbox")
    def on_create_disk_checkbox_changed(self, event: Checkbox.Changed) -> None:
        self.query_one("#disk-size-input", Input).disabled = not event.value
        self.query_one("#disk-format-select", Select).disabled = not event.value

    @on(Checkbox.Changed, "#cdrom-checkbox")
    def on_cdrom_checkbox_changed(self, event: Checkbox.Changed) -> None:
        self.query_one("#create-disk-checkbox").disabled = event.value
        if event.value:
            self.query_one("#create-disk-checkbox").value = False


    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add-btn":
            import re
            disk_path = self.query_one("#disk-path-input", Input).value
            create_disk = self.query_one("#create-disk-checkbox", Checkbox).value
            disk_size_str = self.query_one("#disk-size-input", Input).value
            disk_format = self.query_one("#disk-format-select", Select).value
            is_cdrom = self.query_one("#cdrom-checkbox", Checkbox).value

            numeric_part = re.sub(r'[^0-9]', '', disk_size_str)
            disk_size = int(numeric_part) if numeric_part else 10

            result = {
                "disk_path": disk_path,
                "create": create_disk,
                "size_gb": disk_size,
                "disk_format": disk_format,
                "device_type": "cdrom" if is_cdrom else "disk",
            }
            self.dismiss(result)
        elif event.button.id == "cancel-btn":
            self.dismiss(None)

class AddPoolModal(BaseModal[bool | None]):
    """Modal screen for adding a new storage pool."""

    def __init__(self, conn: libvirt.virConnect) -> None:
        super().__init__()
        self.conn = conn

    def compose(self) -> ComposeResult:
        with Vertical(id="add-pool-dialog", classes="add-pool-dialog"):
            yield Label("Add New Storage Pool")
            yield Input(placeholder="Pool Name (e.g., my_pool)", id="pool-name-input")
            yield Select(
                [
                    ("dir: Filesystem Directory", "dir"),
                    ("netfs: Network Exported Directory", "netfs"),
                ],
                id="pool-type-select",
                prompt="Pool Type",
                value="dir"
            )

            # Fields for `dir` type
            with Vertical(id="dir-fields"):
                yield Label("Target Path (for volumes)")
                with Vertical():
                    yield Input(value="/var/lib/libvirt/images/", id="dir-target-path-input", placeholder="/var/lib/libvirt/images/<pool_name>")
                    yield Button("Browse", id="browse-dir-btn")

            # Fields for `netfs` type
            with Vertical(id="netfs-fields"):
                with ScrollableContainer():
                    yield Label("Target Path (on this host)")
                    with Vertical():
                        yield Input(placeholder="/mnt/nfs", id="netfs-target-path-input")
                        yield Button("Browse", id="browse-netfs-btn")
                    yield Select(
                        [("auto", "auto"), ("nfs", "nfs"), ("glusterfs", "glusterfs"), ("cifs", "cifs")],
                        id="netfs-format-select",
                        value="auto"
                    )
                    yield Label("Source Hostname")
                    yield Input(placeholder="nfs.example.com", id="netfs-host-input")
                    yield Label("Source Path (on remote host)")
                    yield Input(placeholder="host0", id="netfs-source-path-input", value="host0")

            with Horizontal(classes="modal-buttons"):
                yield Button("Add", variant="primary", id="add-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")

    def on_mount(self) -> None:
        self.query_one("#netfs-fields").display = False
        self.query_one("#dir-fields").display = True
    @on(Select.Changed, "#pool-type-select")
    def on_pool_type_select_changed(self, event: Select.Changed) -> None:
        is_dir = event.value == "dir"
        self.query_one("#dir-fields").display = is_dir
        self.query_one("#netfs-fields").display = not is_dir

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id in ("browse-dir-btn", "browse-netfs-btn"):
            input_id = "#dir-target-path-input" if event.button.id == "browse-dir-btn" else "#netfs-target-path-input"
            input_to_update = self.query_one(input_id, Input)

            def on_directory_selected(path: str | None) -> None:
                if path:
                    input_to_update.value = path

            self.app.push_screen(DirectorySelectionModal(path=input_to_update.value), on_directory_selected)
            return

        if event.button.id == "add-btn":
            pool_name = self.query_one("#pool-name-input", Input).value
            pool_type = self.query_one("#pool-type-select", Select).value

            if not pool_name:
                self.app.show_error_message("Pool name is required.")
                return

            pool_details = {"name": pool_name, "type": pool_type}

            if pool_type == "dir":
                target_path = self.query_one("#dir-target-path-input", Input).value
                if not target_path:
                    self.app.show_error_message("Target Path is required for `dir` type.")
                    return
                if target_path == "/var/lib/libvirt/images/":
                    target_path = os.path.join(target_path, pool_name)
                pool_details["target"] = target_path
            elif pool_type == "netfs":
                target_path = self.query_one("#netfs-target-path-input", Input).value
                netfs_format = self.query_one("#netfs-format-select", Select).value
                host = self.query_one("#netfs-host-input", Input).value
                source_path = self.query_one("#netfs-source-path-input", Input).value
                if not all([target_path, host, source_path]):
                    self.app.show_error_message("For `netfs`, all fields are required.")
                    return
                pool_details["target"] = target_path
                pool_details["format"] = netfs_format
                pool_details["host"] = host
                pool_details["source"] = source_path
            try:
                if pool_details['type'] == 'dir':
                    create_storage_pool(
                        self.conn,
                        pool_details['name'],
                        pool_details['type'],
                        pool_details['target']
                    )
                elif pool_details['type'] == 'netfs':
                    create_storage_pool(
                        self.conn,
                        pool_details['name'],
                        pool_details['type'],
                        pool_details['target'],
                        source_host=pool_details['host'],
                        source_path=pool_details['source'],
                        source_format=pool_details['format']
                    )
                self.app.show_success_message(f"Storage pool '{pool_details['name']}' created and started.")
                self.dismiss(True)
            except Exception as e:
                self.app.show_error_message(f"Error creating storage pool: {e}")

        elif event.button.id == "cancel-btn":
            self.dismiss(None)

class CreateVolumeModal(BaseModal[dict | None]):
    """Modal screen for creating a new storage volume."""

    def compose(self) -> ComposeResult:
        with Vertical(id="create-volume-dialog"):
            yield Label("Create New Storage Volume")
            yield Input(placeholder="Volume Name (e.g., new_disk.qcow2)", id="vol-name-input")
            yield Input(placeholder="Size in GB (e.g., 10)", id="vol-size-input", type="integer")
            yield Select([("qcow2", "qcow2"), ("raw", "raw")], id="vol-format-select", value="qcow2")
            with Horizontal():
                yield Button("Create", variant="primary", id="create-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create-btn":
            name = self.query_one("#vol-name-input", Input).value
            size = self.query_one("#vol-size-input", Input).value
            vol_format = self.query_one("#vol-format-select", Select).value

            if not name or not size:
                self.app.show_error_message("Name and size are required.")
                return

            try:
                size_gb = int(size)
            except ValueError:
                self.app.show_error_message("Size must be an integer.")
                return

            self.dismiss({'name': name, 'size_gb': size_gb, 'format': vol_format})
        elif event.button.id == "cancel-btn":
            self.dismiss(None)

class EditDiskModal(BaseModal[dict | None]):
    def __init__(self, disk_info: dict, is_stopped: bool):
        super().__init__()
        self.disk_info = disk_info
        self.is_stopped = is_stopped

    def compose(self) -> ComposeResult:
        cache_options = [("default", "default"), ("none", "none"), ("writethrough", "writethrough"), ("writeback", "writeback"), ("directsync", "directsync"), ("unsafe", "unsafe")]
        discard_options = [("unmap", "unmap"), ("ignore", "ignore")]

        with Vertical(classes="modal-container"):
            yield Label(f"Edit Disk: {self.disk_info['path']}")

            yield Label("Cache Mode:")
            yield Select(cache_options, value=self.disk_info.get('cache', 'none'), id="edit-cache-mode", disabled=not self.is_stopped)

            yield Label("Discard Mode:")
            yield Select(discard_options, value=self.disk_info.get('discard', 'unmap'), id="edit-discard-mode", disabled=not self.is_stopped)

            if not self.is_stopped:
                yield Label("VM must be stopped to edit disk settings.", classes="warning")

            with Horizontal(classes="modal-buttons"):
                yield Button("Apply", variant="primary", id="apply-disk-edit", disabled=not self.is_stopped)
                yield Button("Cancel", id="cancel-disk-edit")

    @on(Button.Pressed, "#apply-disk-edit")
    def on_apply(self):
        result = {
            "cache": self.query_one("#edit-cache-mode", Select).value,
            "discard": self.query_one("#edit-discard-mode", Select).value
        }
        self.dismiss(result)

    @on(Button.Pressed, "#cancel-disk-edit")
    def on_cancel(self):
        self.dismiss(None)
