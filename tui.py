import os
import sys
import logging
import ipaddress
import asyncio
import traceback
from typing import TypeVar

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Select, Button, Input, Label, Static, DataTable, Link, TextArea, ListView, ListItem, Checkbox, RadioButton, RadioSet, TabbedContent, TabPane, Pretty
from textual.containers import ScrollableContainer, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.message import Message
from textual import on
import libvirt
from vmcard import VMCard, VMNameClicked, ConfirmationDialog, ChangeNetworkDialog
from vm_info import get_status, get_vm_description, get_vm_machine_info, get_vm_firmware_info, get_vm_networks_info, get_vm_network_ip, get_vm_network_dns_gateway_info, get_vm_disks_info, get_vm_devices_info, add_disk, remove_disk, set_vcpu, set_memory, get_supported_machine_types, set_machine_type, list_networks, create_network, delete_network, get_vms_using_network, set_network_active, set_network_autostart, get_host_network_interfaces, enable_disk, disable_disk, change_vm_network, get_vm_shared_memory_info, set_shared_memory, remove_virtiofs, add_virtiofs
from config import load_config, save_config

# Configure logging
logging.basicConfig(
    filename='vm_manager.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

T = TypeVar("T")

class BaseModal(ModalScreen[T]):
    BINDINGS = [("escape", "cancel_modal", "Cancel")]

    def action_cancel_modal(self) -> None:
        self.dismiss(None)


class ConnectionModal(BaseModal[str | None]):

    def compose(self) -> ComposeResult:
        with Vertical(id="connection-dialog"):
            yield Label("Enter QEMU Connection URI:")
            yield Input(
                placeholder="qemu+ssh://user@host/system or qemu:///system",
                id="uri-input",
            )
            with Horizontal():
                yield Button("Connect", variant="primary", id="connect-btn", classes="Buttonpage")
                yield Button("Cancel", variant="default", id="cancel-btn", classes="Buttonpage")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "connect-btn":
            uri_input = self.query_one("#uri-input", Input)
            self.dismiss(uri_input.value)
        elif event.button.id == "cancel-btn":
            self.dismiss(None)

class AddServerModal(BaseModal[tuple[str, str] | None]):

    def compose(self) -> ComposeResult:
        with Vertical(id="add-server-dialog"):
            yield Label("Add New Server")
            yield Input(placeholder="Server Name", id="server-name-input")
            yield Input(placeholder="qemu+ssh://user@host/system", id="server-uri-input")
            with Horizontal():
                yield Button("Save", variant="primary", id="save-btn", classes="Buttonpage")
                yield Button("Cancel", variant="default", id="cancel-btn", classes="Buttonpage")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            name_input = self.query_one("#server-name-input", Input)
            uri_input = self.query_one("#server-uri-input", Input)
            self.dismiss((name_input.value, uri_input.value))
        elif event.button.id == "cancel-btn":
            self.dismiss(None)

class EditServerModal(BaseModal[tuple[str, str] | None]):

    def __init__(self, server_name: str, server_uri: str) -> None:
        super().__init__()
        self.server_name = server_name
        self.server_uri = server_uri

    def compose(self) -> ComposeResult:
        with Vertical(id="edit-server-dialog"):
            yield Label("Edit Server")
            yield Input(value=self.server_name, id="server-name-input")
            yield Input(value=self.server_uri, id="server-uri-input")
            with Horizontal():
                yield Button("Save", variant="primary", id="save-btn", classes="Buttonpage")
                yield Button("Cancel", variant="default", id="cancel-btn", classes="Buttonpage")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            name_input = self.query_one("#server-name-input", Input)
            uri_input = self.query_one("#server-uri-input", Input)
            self.dismiss((name_input.value, uri_input.value))
        elif event.button.id == "cancel-btn":
            self.dismiss(None)

class ServerSelectionModal(BaseModal[str | None]):

    def __init__(self, servers: list) -> None:
        super().__init__()
        self.servers = servers
        self.selected_uri = None

    def compose(self) -> ComposeResult:
        with Vertical(id="server-selection-dialog"):
            yield Label("Select Server")
            with ScrollableContainer():
                yield DataTable(id="server-select-table")
            with Horizontal():
                yield Button("Connect", id="select-btn", variant="primary", disabled=True, classes="Buttonpage")
                yield Button("Custom URL", id="custom-conn-btn", classes="Buttonpage")
                yield Button("Cancel", id="cancel-btn", classes="Buttonpage")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        table.add_column("Name", key="name")
        table.add_column("URI", key="uri")
        for server in self.servers:
            table.add_row(server['name'], server['uri'], key=server['uri'])
        table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.selected_uri = event.row_key.value
        self.query_one("#select-btn").disabled = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "select-btn":
            self.dismiss(self.selected_uri)
        elif event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "custom-conn-btn":
            def connection_callback(uri: str | None):
                if uri:
                    self.dismiss(uri)
            self.app.push_screen(ConnectionModal(), connection_callback)


class FilterModal(BaseModal[dict | None]):
    """Modal screen for selecting a filter."""

    def __init__(self, current_search: str = "", current_status: str = "default") -> None:
        super().__init__()
        self.current_search = current_search
        self.current_status = current_status

    def compose(self) -> ComposeResult:
        with Vertical(id="filter-dialog"): #, classes="FilterModal"):
            yield Label("Filter by Name")
            yield Input(placeholder="Enter VM name...", id="search-input", value=self.current_search)
            with RadioSet(id="status-radioset"):
                yield RadioButton("All", id="status_default", value=self.current_status == "default")
                yield RadioButton("Running", id="status_running", value=self.current_status == "running")
                yield RadioButton("Paused", id="status_paused", value=self.current_status == "paused")
                yield RadioButton("Stopped", id="status_stopped", value=self.current_status == "stopped")
            with Horizontal():
                yield Button("Apply", id="apply-btn", variant="success")
                yield Button("Cancel", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "apply-btn":
            search_text = self.query_one("#search-input", Input).value
            radioset = self.query_one(RadioSet)
            status_button = radioset.pressed_button
            status = "default"
            if status_button:
                status = status_button.id.replace("status_", "")

            self.dismiss({'status': status, 'search': search_text})


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


class ServerManagementModal(ModalScreen):
    """Modal screen for managing servers."""

    BINDINGS = [("escape", "close_modal", "Close")]

    def __init__(self, servers: list) -> None:
        super().__init__()
        self.servers = servers
        self.selected_row = None

    def compose(self) -> ComposeResult:
        with Vertical(id="server-management-dialog"):
            yield Label("Server List Management", classes="server-list")
            with ScrollableContainer():
                yield DataTable(id="server-table")
            with Horizontal():
                yield Button("Add", id="add-server-btn", classes="add-button")
                yield Button("Edit", id="edit-server-btn", disabled=True, classes="edit-button")
                yield Button("Delete", id="delete-server-btn", disabled=True, classes="delete-button")
            yield Button("Close", id="close-btn", classes="close-button")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        table.add_column("Name", key="name")
        table.add_column("URI", key="uri")
        for server in self.servers:
            table.add_row(server['name'], server['uri'], key=server['uri'])
        table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.selected_row = event.cursor_row
        self.query_one("#edit-server-btn").disabled = False
        self.query_one("#delete-server-btn").disabled = False

    def _reload_table(self):
        table = self.query_one(DataTable)
        table.clear()
        for server in self.servers:
            table.add_row(server['name'], server['uri'], key=server['uri'])

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-btn":
            self.dismiss(self.servers)
        elif event.button.id == "add-server-btn":
            def add_server_callback(result):
                if result:
                    name, uri = result
                    self.servers.append({'name': name, 'uri': uri})
                    self.app.config['servers'] = self.servers
                    save_config(self.app.config)
                    self._reload_table()
            self.app.push_screen(AddServerModal(), add_server_callback)
        elif event.button.id == "edit-server-btn" and self.selected_row is not None:
            server_to_edit = self.servers[self.selected_row]
            def edit_server_callback(result):
                if result:
                    new_name, new_uri = result
                    self.servers[self.selected_row]['name'] = new_name
                    self.servers[self.selected_row]['uri'] = new_uri
                    self.app.config['servers'] = self.servers
                    save_config(self.app.config)
                    self._reload_table()
            self.app.push_screen(EditServerModal(server_to_edit['name'], server_to_edit['uri']), edit_server_callback)
        elif event.button.id == "delete-server-btn" and self.selected_row is not None:
            server_to_delete = self.servers[self.selected_row]
            server_name_to_delete = server_to_delete['name']

            def on_confirm(confirmed: bool) -> None:
                if confirmed:
                    try:
                        del self.servers[self.selected_row]
                        self.app.config['servers'] = self.servers
                        save_config(self.app.config)
                        self._reload_table()
                        self.selected_row = None
                        self.query_one("#edit-server-btn").disabled = True
                        self.query_one("#delete-server-btn").disabled = True
                        self.app.show_success_message(f"Server '{server_name_to_delete}' deleted successfully.")
                        logging.info(f"Successfully deleted Server '{server_name_to_delete}'")
                    except Exception as e:
                        self.app.show_error_message(f"Error deleting server '{server_name_to_delete}': {e}")

            self.app.push_screen(
                ConfirmationDialog(f"Are you sure you want to delete Server '{server_name_to_delete}' from list?"), on_confirm)


    def action_close_modal(self) -> None:
        """Close the modal."""
        self.dismiss(self.servers)

class LogModal(BaseModal[None]):
    """ Modal Screen to show Log"""

    def compose(self) -> ComposeResult:
        with Vertical(id="text-show"):
            yield Label("Log View", id="title")
            log_file = "vm_manager.log"
            text_area = TextArea()
            text_area.load_text(open(log_file, "r").read())
            yield text_area
        with Horizontal():
            yield Button("Cancel", variant="default", id="cancel-btn", classes="Buttonpage")

    def on_mount(self) -> None:
        """Called when the modal is mounted."""
        text_area = self.query_one(TextArea)
        text_area.scroll_end()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
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

class AddEditVirtIOFSModal(BaseModal[dict | None]):
    """Modal screen for adding or editing a VirtIO-FS mount."""

    def __init__(self, source_path: str = "", target_path: str = "", readonly: bool = False, is_edit: bool = False) -> None:
        super().__init__()
        self.source_path = source_path
        self.target_path = target_path
        self.readonly = readonly
        self.is_edit = is_edit

    def compose(self) -> ComposeResult:
        with Vertical(id="add-edit-virtiofs-dialog"):
            yield Label("Edit VirtIO-FS Mount" if self.is_edit else "Add VirtIO-FS Mount")
            yield Input(placeholder="Source Path (e.g., /mnt/share)", id="virtiofs-source-input", value=self.source_path)
            yield Input(placeholder="Target Path (e.g., /share)", id="virtiofs-target-input", value=self.target_path)
            yield Checkbox("Export filesystem as readonly mount", id="virtiofs-readonly-checkbox", value=self.readonly)
            with Horizontal():
                yield Button("Save" if self.is_edit else "Add", variant="primary", id="save-add-btn", classes="Buttonpage")
                yield Button("Cancel", variant="default", id="cancel-btn", classes="Buttonpage")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-add-btn":
            source_path = self.query_one("#virtiofs-source-input", Input).value
            target_path = self.query_one("#virtiofs-target-input", Input).value
            readonly = self.query_one("#virtiofs-readonly-checkbox", Checkbox).value

            if not source_path or not target_path:
                self.app.show_error_message("Source Path and Target Path cannot be empty.")
                return

            self.dismiss({'source_path': source_path, 'target_path': target_path, 'readonly': readonly})
        elif event.button.id == "cancel-btn":
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


class EditCpuModal(BaseModal[str | None]):
    """Modal screen for editing VCPU count."""

    def __init__(self, current_cpu: str = "") -> None:
        super().__init__()
        self.current_cpu = current_cpu

    def compose(self) -> ComposeResult:
        with Vertical(id="edit-cpu-dialog"):
            yield Label("Enter new VCPU count:")
            yield Input(placeholder="e.g., 2", id="cpu-input", type="integer", value=self.current_cpu)
            with Horizontal():
                yield Button("Save", variant="primary", id="save-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            cpu_input = self.query_one("#cpu-input", Input)
            self.dismiss(cpu_input.value)
        elif event.button.id == "cancel-btn":
            self.dismiss(None)


class EditMemoryModal(BaseModal[str | None]):
    """Modal screen for editing memory size."""

    def __init__(self, current_memory: str = "") -> None:
        super().__init__()
        self.current_memory = current_memory

    def compose(self) -> ComposeResult:
        with Vertical(id="edit-memory-dialog"):
            yield Label("Enter new memory size (MB):")
            yield Input(placeholder="e.g., 2048", id="memory-input", type="integer", value=self.current_memory)
            with Horizontal():
                yield Button("Save", variant="primary", id="save-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            memory_input = self.query_one("#memory-input", Input)
            self.dismiss(memory_input.value)
        elif event.button.id == "cancel-btn":
            self.dismiss(None)

class SelectMachineTypeModal(BaseModal[str | None]):
    """Modal screen for selecting machine type."""

    def __init__(self, machine_types: list[str], current_machine_type: str = "") -> None:
        super().__init__()
        self.machine_types = machine_types
        self.current_machine_type = current_machine_type

    def compose(self) -> ComposeResult:
        with Vertical(id="select-machine-type-dialog"):
            yield Label("Select Machine Type:")
            with ScrollableContainer():
                yield ListView(
                    *[ListItem(Label(mt)) for mt in self.machine_types],
                    id="machine-type-list"
                )
            with Horizontal():
                yield Button("Cancel", variant="default", id="cancel-btn")

    def on_mount(self) -> None:
        list_view = self.query_one(ListView)
        try:
            current_index = self.machine_types.index(self.current_machine_type)
            list_view.index = current_index
        except (ValueError, IndexError):
            pass

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.dismiss(str(event.item.query_one(Label).renderable))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)

class NetworkListItem(ListItem):
    """A list item that displays network information with interactive toggles."""

    class NetworkStatusChanged(Message):
        """Event sent when the active or autostart status of a network changes."""
        def __init__(self, network_name: str, change_type: str, value: bool) -> None:
            super().__init__()
            self.network_name = network_name
            self.change_type = change_type
            self.value = value

    def __init__(self, net_info: dict) -> None:
        super().__init__()
        self.net_info = net_info
        self.network_name = net_info['name']

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label(self.net_info['name'], classes="net-name")
            yield Label(self.net_info['mode'], classes="net-mode")
            yield Checkbox("Active", self.net_info['active'], id="net-active-check")
            yield Checkbox("Autostart", self.net_info['autostart'], id="net-autostart-check")

    @on(Checkbox.Changed)
    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        change_type = "active" if event.checkbox.id == "net-active-check" else "autostart"

class CreateNatNetworkModal(BaseModal[None]):
    """Modal screen for creating a new NAT network."""

    def compose(self) -> ComposeResult:
        with Vertical(id="create-nat-network-dialog"):
            yield Label("Create New NAT Network", id="create-nat-network-title")

            host_interfaces = get_host_network_interfaces()
            if not host_interfaces:
                host_interfaces = [("No interfaces found", "")]
            interface_options = []
            for name, ip in host_interfaces:
                display_text = f"{name} ({ip})" if ip else name
                interface_options.append((display_text, name))

            with ScrollableContainer():
                with Vertical(id="create-network-form"):
                    yield Input(placeholder="Network Name (e.g., nat_net)", id="net-name-input")
                    with RadioSet(id="type-network", classes="type-network-radioset"):
                        yield RadioButton("Nat network", id="type-network-nat", value=True)
                        yield RadioButton("Routed network", id="type-network-routed")
                    yield Select(interface_options, prompt="Select Forward Interface", id="net-forward-input", classes="net-forward-input")
                    yield Input(placeholder="IPv4 Network (e.g., 192.168.100.0/24)", id="net-ip-input", value="192.168.11.0/24")
                    yield Checkbox("Enable DHCPv4", id="dhcp-checkbox", value=True)
                    with Vertical(id="dhcp-inputs-horizontal"):
                        with Horizontal(id="dhcp-options"):
                            yield Input(placeholder="DHCP Start (e.g., 192.168.100.100)", id="dhcp-start-input", classes="dhcp-input", value="192.168.11.10")
                            yield Input(placeholder="DHCP End (e.g., 192.168.100.254)", id="dhcp-end-input", classes="dhcp-input", value="192.168.11.30")
                    with RadioSet(id="dns-domain-radioset", classes="dns-domain-radioset"):
                        yield RadioButton("Use Network Name for DNS Domain", id="dns-use-net-name", value=True)
                        yield RadioButton("Use Custom DNS Domain", id="dns-use-custom")
                    yield Input(placeholder="Custom DNS Domain", id="dns-custom-domain-input", classes="hidden")
                    with Vertical(id="network-create-close-horizontal"):
                        with Horizontal(id="dhcp-options"):
                            yield Button("Create Network", variant="primary", id="create-net-btn", classes="create-net-btn")
                            yield Button("Close", variant="default", id="close-btn", classes="close-button")

    @on(Checkbox.Changed, "#dhcp-checkbox")
    def on_dhcp_checkbox_changed(self, event: Checkbox.Changed) -> None:
        dhcp = self.query_one("#dhcp-checkbox", Checkbox).value
        dhcp_options = self.query_one("#dhcp-options")
        if dhcp:
            dhcp_options.remove_class("hidden")
        else:
            dhcp_options.add_class("hidden")

    @on(RadioSet.Changed, "#dns-domain-radioset")
    def on_dns_domain_radioset_changed(self, event: RadioSet.Changed) -> None:
        custom_domain_input = self.query_one("#dns-custom-domain-input")
        if event.pressed.id == "dns-use-custom":
            custom_domain_input.remove_class("hidden")
        else:
            custom_domain_input.add_class("hidden")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-btn":
            self.dismiss(None)
        elif event.button.id == "create-net-btn":
            name = self.query_one("#net-name-input", Input).value
            typenet_id = self.query_one("#type-network", RadioSet).pressed_button.id
            if typenet_id == "type-network-nat":
                typenet = "nat"
            elif typenet_id == "type-network-routed":
                typenet = "route"
            else:
                self.app.show_error_message(f"Unknown network type: {typenet_id}")
                return
            forward_select = self.query_one("#net-forward-input", Select)
            forward = forward_select.value
            ip = self.query_one("#net-ip-input", Input).value
            dhcp = self.query_one("#dhcp-checkbox", Checkbox).value
            dhcp_start = self.query_one("#dhcp-start-input", Input).value
            dhcp_end = self.query_one("#dhcp-end-input", Input).value

            domain_radio = self.query_one("#dns-domain-radioset", RadioSet).pressed_button.id
            domain_name = name
            if domain_radio == "dns-use-custom":
                domain_name = self.query_one("#dns-domain-input", Input).value

            try:
                # Validate network address
                ip_network = ipaddress.ip_network(ip, strict=False)

                if dhcp:
                    # Validate DHCP start and end IPs
                    dhcp_start_ip = ipaddress.ip_address(dhcp_start)
                    dhcp_end_ip = ipaddress.ip_address(dhcp_end)

                    # Check if DHCP IPs are within the network
                    if dhcp_start_ip not in ip_network:
                        self.app.show_error_message(f"DHCP start IP {dhcp_start_ip} is not in the network {ip_network}")
                        return
                    if dhcp_end_ip not in ip_network:
                        self.app.show_error_message(f"DHCP end IP {dhcp_end_ip} is not in the network {ip_network}")
                        return
                    if dhcp_start_ip >= dhcp_end_ip:
                        self.app.show_error_message("DHCP start IP must be before the end IP.")
                        return

            except ValueError as e:
                self.app.show_error_message(f"Invalid IP address or network: {e}")
                return

            try:
                create_network(self.app.conn, name, typenet, forward, ip, dhcp, dhcp_start, dhcp_end, domain_name)
                self.app.show_success_message(f"Network {name} created successfully.")
                self.dismiss(True) # True to indicate success
            except Exception as e:
                self.app.show_error_message(f"Error creating network: {e}")

class ServerPrefModal(BaseModal[None]):
    """Modal screen for server preferences."""

    def compose(self) -> ComposeResult:
        with Vertical(id="server-pref-dialog", classes="ServerPrefModal"):
            yield Label("Server Preferences", id="server-pref-title")
            with TabbedContent(id="server-pref-tabs"):
                with TabPane("Network", id="tab-network"):
                    with ScrollableContainer():
                        yield ListView(id="existing-networks-list", classes="info-network-pref")
                    with Horizontal(id="network-buttons"):
                        yield Button("Add", id="add-net-btn", classes="Buttonpage")
                        yield Button("View", id="view-net-btn", classes="Buttonpage", disabled=True)
                        yield Button("Delete", id="delete-net-btn", variant="error", classes="Buttonpage", disabled=True)
                        yield Button("Close", id="close-btn", classes="Buttonpage")
                with TabPane("Storage", id="tab-storage"):
                    yield Label("Storage settings... WIP")

    def on_mount(self) -> None:
        self._load_networks()

    def _load_networks(self):
        list_view = self.query_one("#existing-networks-list", ListView)
        list_view.clear()
        networks = list_networks(self.app.conn)
        for net in networks:
            list_view.append(NetworkListItem(net))
        list_view.focus()

    @on(ListView.Selected, "#existing-networks-list")
    def on_list_view_selected(self, event: ListView.Selected):
        self.query_one("#view-net-btn").disabled = False
        self.query_one("#delete-net-btn").disabled = False

    @on(NetworkListItem.NetworkStatusChanged)
    def on_network_status_changed(self, event: NetworkListItem.NetworkStatusChanged) -> None:
        try:
            if event.change_type == "active":
                set_network_active(self.app.conn, event.network_name, event.value)
                self.app.show_success_message(f"Network {event.network_name} activity set to {event.value}")
            elif event.change_type == "autostart":
                set_network_autostart(self.app.conn, event.network_name, event.value)
                self.app.show_success_message(f"Network {event.network_name} autostart set to {event.value}")
        except Exception as e:
            self.app.show_error_message(str(e))
            self._load_networks() # Reload to show the correct state
            self.app.show_error_message(f"An unexpected error occurred: {e}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-btn":
            self.dismiss(None)
        elif event.button.id == "view-net-btn":
            list_view = self.query_one("#existing-networks-list", ListView)
            if list_view.index is None:
                return

            selected_item = list_view.children[list_view.index]
            network_name = selected_item.network_name
            try:
                conn = self.app.conn
                if conn is None:
                    self.app.show_error_message("Not connected to libvirt.")
                    return
                net = conn.networkLookupByName(network_name)
                network_xml = net.XMLDesc(0)
                self.app.push_screen(NetworkXMLModal(network_name, network_xml))
            except libvirt.libvirtError as e:
                self.app.show_error_message(f"Error getting network XML: {e}")
            except Exception as e:
                self.app.show_error_message(f"An unexpected error occurred: {e}")

        elif event.button.id == "add-net-btn":
            def on_create(success: bool):
                if success:
                    self._load_networks()
            self.app.push_screen(CreateNatNetworkModal(), on_create)
        elif event.button.id == "delete-net-btn":
            list_view = self.query_one("#existing-networks-list", ListView)
            if list_view.index is None:
                return

            selected_item = list_view.children[list_view.index]
            network_name = selected_item.network_name
            vms_using_network = get_vms_using_network(self.app.conn, network_name)
            
            confirm_message = f"Are you sure you want to delete network '{network_name}'?"
            if vms_using_network:
                vm_list = ", ".join(vms_using_network)
                confirm_message += f"\nThis network is currently in use by the following VMs:\n{vm_list}."

            def on_confirm(confirmed: bool) -> None:
                if confirmed:
                    try:
                        delete_network(self.app.conn, network_name)
                        self.app.show_success_message(f"Network '{network_name}' deleted successfully.")
                        self._load_networks()
                    except Exception as e:
                        self.app.show_error_message(f"Error deleting network '{network_name}': {e}")

            self.app.push_screen(
                ConfirmationDialog(confirm_message), on_confirm
            )



class VMDetailModal(ModalScreen):
    """Modal screen to show detailed VM information."""

    BINDINGS = [("escape", "close_modal", "Close")]

    def __init__(self, vm_name: str, vm_info: dict, domain: libvirt.virDomain) -> None:
        super().__init__()
        self.vm_name = vm_name
        self.vm_info = vm_info
        self.domain = domain
        self.available_networks = []
        self.selected_virtiofs_target = None
        self.selected_virtiofs_info = None # Store full info for editing


    def on_mount(self) -> None:
        try:
            all_networks_info = list_networks(self.app.conn)
            self.available_networks = [net['name'] for net in all_networks_info]
        except (libvirt.libvirtError, Exception) as e:
            self.app.show_error_message(f"Could not load networks: {e}")
            self.available_networks = []

    @on(Select.Changed)
    def on_network_change(self, event: Select.Changed) -> None:
        if not event.control.id or not event.control.id.startswith("net-select-"):
            return

        mac_address_flat = event.control.id.replace("net-select-", "")
        mac_address = ":".join(mac_address_flat[i:i+2] for i in range(0, len(mac_address_flat), 2))
        new_network = event.value
        original_network = ""

        for i in self.vm_info["networks"]:
            if i["mac"] == mac_address:
                original_network = i["network"]
                break
        
        if original_network == new_network:
            return

        try:
            change_vm_network(self.domain, mac_address, new_network)
            self.app.show_success_message(f"Interface {mac_address} switched to {new_network}")
            for i in self.vm_info["networks"]:
                if i["mac"] == mac_address:
                    i["network"] = new_network
                    break
        except (libvirt.libvirtError, ValueError, Exception) as e:
            self.app.show_error_message(f"Error updating network: {e}")
            event.control.value = original_network

        self.available_networks = []

    @on(Checkbox.Changed, "#shared-memory-checkbox")
    def on_shared_memory_changed(self, event: Checkbox.Changed) -> None:
        try:
            set_shared_memory(self.domain, event.value)
            self.app.show_success_message(f"Shared memory {'enabled' if event.value else 'disabled'}.")
            self.vm_info['shared_memory'] = event.value
        except (libvirt.libvirtError, ValueError, Exception) as e:
            self.app.show_error_message(f"Error setting shared memory: {e}")
            # Revert checkbox state on failure
            event.checkbox.value = not event.value

    def compose(self) -> ComposeResult:
        with Vertical(id="vm-detail-container"):
            yield Label(f"VM Details: {self.vm_name}", id="title")
            yield Label(f"UUID: {self.vm_info.get('uuid', 'N/A')}")
            status = self.vm_info.get("status", "N/A")
            yield Label(f"Status: {status}", id=f"status-{status.lower().replace(' ', '-')}", classes="centered-status-label")
            with TabbedContent(id="detail-vm"):
                with TabPane("CPU", id="detail-cpu-tab"):
                    with Vertical(classes="info-details"):
                        yield Label(f"CPU: {self.vm_info.get('cpu', 'N/A')}", id="cpu-label", classes="tabd")
                        yield Button("Edit", id="edit-cpu", classes="edit-detail-btn")
                with TabPane("Mem", id="detail-mem-tab", ):
                    with Vertical(classes="info-details"):
                        yield Label(f"Memory: {self.vm_info.get('memory', 'N/A')} MB", id="memory-label", classes="tabd")
                        yield Button("Edit", id="edit-memory", classes="edit-detail-btn")
                        is_stopped = self.vm_info.get("status") == "Stopped"
                        yield Checkbox("Shared Memory", value=self.vm_info.get('shared_memory', False), id="shared-memory-checkbox", classes="shared-memory", disabled=not is_stopped)
                with TabPane("Firmware", id="detail-firmware-tab"):
                    with Vertical(classes="info-details"): 
                        if "firmware" in self.vm_info:
                            yield Label(f"Firmware: {self.vm_info['firmware']}", classes="tabd")
                        if "machine_type" in self.vm_info:
                            yield Label(f"Machine Type: {self.vm_info['machine_type']}", id="machine-type-label", classes="tabd")
                            is_stopped = self.vm_info.get("status") == "Stopped"
                            yield Button("Edit", id="edit-machine-type", classes="edit-detail-btn", disabled=not is_stopped)

                with TabPane("Boot", id="detail-boot-tab"):
                    yield Label("TODO", classes="tabd")

                with TabPane("Disks", id="detail-disk-tab"):
                    with ScrollableContainer(classes="info-details"):
                        disks_info = self.vm_info.get("disks", [])
                        disk_items = []
                        for disk in disks_info:
                            path = disk.get('path', 'N/A')
                            status = disk.get('status', 'unknown')
                            label = f"{path}"
                            if status == 'disabled':
                                label += " (disabled)"
                            disk_items.append(ListItem(Label(label)))

                        self.disk_list_view = ListView(*disk_items)
                        num_disks = len(disks_info)
                        self.disk_list_view.styles.height = num_disks if num_disks > 0 else 1
                        if not disks_info:
                            self.disk_list_view.append(ListItem(Label("No disks found.")))
                        yield self.disk_list_view
                    with Horizontal():
                        has_enabled_disks = any(d['status'] == 'enabled' for d in disks_info)
                        has_disabled_disks = any(d['status'] == 'disabled' for d in disks_info)
                        remove_button = Button("Remove Disk", id="detail_remove_disk", classes="detail-disks")
                        disable_button = Button("Disable Disk", id="detail_disable_disk", classes="detail-disks")
                        enable_button = Button("Enable Disk", id="detail_enable_disk", classes="detail-disks")
                        remove_button.display = has_enabled_disks
                        disable_button.display = has_enabled_disks
                        enable_button.display = has_disabled_disks

                        with Vertical():
                            with Horizontal():
                                yield Button("Add Disk", id="detail_add_disk", classes="detail-disks")
                                yield remove_button
                                yield disable_button
                                yield enable_button

                with TabPane("Networks", id="networks"):
                    with ScrollableContainer(classes="info-details"):
                        networks_list = self.vm_info.get("networks", [])
                        detail_network_list = self.vm_info.get("detail_network", [])
                        mac_to_ip = {}
                        if detail_network_list:
                            for detail in detail_network_list:
                                ips = detail.get('ipv4', []) + detail.get('ipv6', [])
                                if ips:
                                    mac_to_ip[detail['mac']] = ", ".join(ips)

                        if networks_list:
                            for net in networks_list:
                                yield Label(f"MAC: {net['mac']}", classes="tabd")
                                yield Label(f"Network: {net.get('network', 'N/A')}", classes="tabd")
                                ip_address = mac_to_ip.get(net['mac'], "N/A")
                                yield Label(f"IP: {ip_address}", classes="tabd")
                                yield Static(classes="separator")
                        else:
                            yield Label("No network interfaces found.")
                    yield Button("Change Network", id="change-network-button", variant="primary")

                    if self.vm_info.get("network_dns_gateway"):
                        yield Label("Network DNS & Gateway", classes="tabd")
                        with ScrollableContainer(classes="info-section"):
                            for net_detail in self.vm_info["network_dns_gateway"]:
                                with Vertical(classes="info-details"):
                                    yield Static(f"  Network: {net_detail.get('network_name', 'N/A')}")
                                    if net_detail.get("gateway"):
                                        yield Static(f"    Gateway: {net_detail['gateway']}")
                                    if net_detail.get("dns_servers"):
                                        yield Static("    DNS Servers:")
                                        for dns_server in net_detail["dns_servers"]:
                                            yield Static(f"      • {dns_server}")

                if self.vm_info.get("devices"):
                    with TabPane("Devices", id="detail-devices-tab"):
                        with ScrollableContainer(classes="info-details"):
                            for device_type, device_list in self.vm_info["devices"].items():
                                if device_type == "virtiofs":
                                    pass
                                else:
                                    yield Static(f"  {device_type.replace('_', ' ').title()}:")
                                    for device in device_list:
                                        detail_str = ", ".join(f"{k}: {v}" for k, v in device.items())
                                        yield Static(f"    • {detail_str}")

                if self.vm_info.get("devices"):
                    with TabPane("VirtIO-FS", id="detail-virtiofs-tab"):
                        if self.vm_info.get('shared_memory') == False:
                            yield Label("! Shared Memory is Mandatory to use VirtIO-FS.\n! Enable it in Mem tab.", classes="tabd-warning")
                        with ScrollableContainer(classes="info-details"):
                            virtiofs_table = DataTable(id="virtiofs-table")
                            virtiofs_table.cursor_type = "row"
                            virtiofs_table.add_column("Source Path", key="source")
                            virtiofs_table.add_column("Target Path", key="target")
                            virtiofs_table.add_column("Readonly", key="readonly")
                            for fs in self.vm_info["devices"]["virtiofs"]:
                                virtiofs_table.add_row(
                                    fs.get('source', 'N/A'),
                                    fs.get('target', 'N/A'),
                                    str(fs.get('readonly', False)),
                                    key=fs.get('target')
                                )
                            yield virtiofs_table
                        with Vertical():
                            with Horizontal():
                                yield Button("Add", variant="primary", id="add-virtiofs-btn", classes="detail-disks")
                                yield Button("Edit", variant="default", id="edit-virtiofs-btn", disabled=True, classes="detail-disks")
                                yield Button("Delete", variant="error", id="delete-virtiofs-btn", disabled=True, classes="detail-disks")
                                yield Button("Close", variant="default", id="close-btn", classes="detail-disks")

        #    with TabbedContent(id="detail2-vm"):
        # TOFIX !
                with TabPane("Video", id="detail-video-tab"):
                    yield Label("Video")
                with TabPane("Serial", id="detail-serial-tab"):
                    yield Label("Serial")
                with TabPane("Sound", id="detail-sound-tab"):
                    yield Label("Sound")
                with TabPane("Watchdog", id="detail-watchdog-tab"):
                    yield Label("Watchdog")
                with TabPane("RNG", id="detail-rng-tab"):
                    yield Label("RNG")
                with TabPane("Input", id="detail-input-tab"):
                    yield Label("Input")
                with TabPane("USB", id="detail-usb-tab"):
                    yield Label("USB")
                with TabPane("USB Host", id="detail-usbhost-tab"):
                    yield Label("USB Host")
                with TabPane("PCI Host", id="detail-PCIhost-tab"):
                    yield Label("PCI Host")
                with TabPane("PCIe", id="detail-pcie-tab"):
                    yield Label("PCIe")
                with TabPane("SATA", id="detail-sata-tab"):
                    yield Label("SATA")
                with TabPane("Channel", id="detail-channel-tab"):
                    yield Label("Channel")

            
    def _update_disk_list(self):
        self.disk_list_view.clear()
        new_xml = self.domain.XMLDesc(0)
        disks_info = get_vm_disks_info(new_xml)
        self.vm_info['disks'] = disks_info  # Update the stored info

        disk_items = []
        for disk in disks_info:
            path = disk.get('path', 'N/A')
            status = disk.get('status', 'unknown')
            label = f"{path}"
            if status == 'disabled':
                label += " (disabled)"
            disk_items.append(ListItem(Label(label)))

        if disk_items:
            for item in disk_items:
                self.disk_list_view.append(item)
        else:
            self.disk_list_view.append(ListItem(Label("No disks found.")))

        num_disks = len(disks_info)
        self.disk_list_view.styles.height = num_disks if num_disks > 0 else 1

        # Update button visibility
        has_enabled_disks = any(d['status'] == 'enabled' for d in disks_info)
        has_disabled_disks = any(d['status'] == 'disabled' for d in disks_info)

        self.query_one("#detail_remove_disk", Button).display = has_enabled_disks
        self.query_one("#detail_disable_disk", Button).display = has_enabled_disks
        self.query_one("#detail_enable_disk", Button).display = has_disabled_disks

        self.query_one("#detail_enable_disk", Button).display = has_disabled_disks

    @on(DataTable.RowSelected, "#virtiofs-table")
    def on_virtiofs_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.selected_virtiofs_target = event.row_key.value
        # Get the full virtiofs info for editing
        row_index = event.cursor_row
        virtiofs_data = self.vm_info["devices"]["virtiofs"]
        if 0 <= row_index < len(virtiofs_data):
            self.selected_virtiofs_info = virtiofs_data[row_index]
        else:
            self.selected_virtiofs_info = None

        self.query_one("#delete-virtiofs-btn", Button).disabled = False
        self.query_one("#edit-virtiofs-btn", Button).disabled = False


    def _update_virtiofs_table(self) -> None:
        """Refreshes the virtiofs table."""
        virtiofs_table = self.query_one("#virtiofs-table", DataTable)
        virtiofs_table.clear()
        
        # Re-fetch VM info to get updated virtiofs list
        new_xml = self.domain.XMLDesc(0)
        updated_devices = get_vm_devices_info(new_xml)
        self.vm_info['devices']['virtiofs'] = updated_devices.get('virtiofs', [])

        for fs in self.vm_info["devices"]["virtiofs"]:
            virtiofs_table.add_row(
                fs.get('source', 'N/A'),
                fs.get('target', 'N/A'),
                str(fs.get('readonly', False)),
                key=fs.get('target')
            )
        self.selected_virtiofs_target = None
        self.selected_virtiofs_info = None
        self.query_one("#delete-virtiofs-btn", Button).disabled = True
        self.query_one("#edit-virtiofs-btn", Button).disabled = True


    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-btn":
            self.dismiss()
        elif event.button.id == "add-virtiofs-btn":
            def add_virtiofs_callback(result):
                if result:
                    try:
                        # VM must be stopped to add virtiofs
                        if self.domain.isActive():
                            self.app.show_error_message("VM must be stopped to add VirtIO-FS mount.")
                            return
                        add_virtiofs(
                            self.domain,
                            result['source_path'],
                            result['target_path'],
                            result['readonly']
                        )
                        self.app.show_success_message(f"VirtIO-FS mount '{result['target_path']}' added successfully.")
                        self._update_virtiofs_table()
                    except libvirt.libvirtError as e:
                        self.app.show_error_message(f"Error adding VirtIO-FS mount: {e}")
                    except Exception as e:
                        self.app.show_error_message(f"An unexpected error occurred: {e}")
            self.app.push_screen(AddEditVirtIOFSModal(is_edit=False), add_virtiofs_callback)

        elif event.button.id == "edit-virtiofs-btn":
            if self.selected_virtiofs_info:
                current_source = self.selected_virtiofs_info.get('source', '')
                current_target = self.selected_virtiofs_info.get('target', '')
                current_readonly = self.selected_virtiofs_info.get('readonly', False)

                def edit_virtiofs_callback(result):
                    if result:
                        try:
                            # VM must be stopped to modify virtiofs
                            if self.domain.isActive():
                                self.app.show_error_message("VM must be stopped to modify VirtIO-FS mount.")
                                return

                            # Only proceed if there are actual changes
                            if (result['source_path'] != current_source or
                                result['target_path'] != current_target or
                                result['readonly'] != current_readonly):
                                
                                # Remove the old one
                                remove_virtiofs(self.domain, current_target)
                                # Add the new one
                                add_virtiofs(
                                    self.domain,
                                    result['source_path'],
                                    result['target_path'],
                                    result['readonly']
                                )
                                self.app.show_success_message(f"VirtIO-FS mount '{current_target}' updated to '{result['target_path']}'.")
                                self._update_virtiofs_table()
                            else:
                                self.app.show_success_message("No changes detected for VirtIO-FS mount.")

                        except libvirt.libvirtError as e:
                            self.app.show_error_message(f"Error editing VirtIO-FS mount: {e}")
                        except Exception as e:
                            self.app.show_error_message(f"An unexpected error occurred: {e}")
                
                self.app.push_screen(AddEditVirtIOFSModal(
                    source_path=current_source,
                    target_path=current_target,
                    readonly=current_readonly,
                    is_edit=True
                ), edit_virtiofs_callback)
            else:
                self.app.show_error_message("No VirtIO-FS mount selected for editing.")

        elif event.button.id == "delete-virtiofs-btn":
            if self.selected_virtiofs_target:
                message = f"Are you sure you want to delete VirtIO-FS mount '{self.selected_virtiofs_target}'?\nVM must be stopped!"
                def on_confirm(confirmed: bool) -> None:
                    if confirmed:
                        try:
                            # VM must be stopped to delete virtiofs
                            if self.domain.isActive():
                                self.app.show_error_message("VM must be stopped to delete VirtIO-FS mount.")
                                return

                            remove_virtiofs(self.domain, self.selected_virtiofs_target)
                            self.app.show_success_message(f"VirtIO-FS mount '{self.selected_virtiofs_target}' deleted successfully.")
                            self._update_virtiofs_table()
                        except libvirt.libvirtError as e:
                            self.app.show_error_message(f"Error deleting VirtIO-FS mount: {e}")
                        except Exception as e:
                            self.app.show_error_message(f"An unexpected error occurred: {e}")
                self.app.push_screen(ConfirmationDialog(message), on_confirm)

        elif event.button.id == "detail_add_disk":
            def add_disk_callback(result):
                if result:
                    try:
                        target_dev = add_disk(
                            self.domain,
                            result["disk_path"],
                            device_type=result["device_type"],
                            create=result["create"],
                            size_gb=result["size_gb"],
                            disk_format=result["disk_format"],
                        )
                        self.app.show_success_message(f"Disk added as {target_dev}")
                        self._update_disk_list()
                    except Exception as e:
                        self.app.show_error_message(f"Error adding disk: {e}")
            self.app.push_screen(AddDiskModal(), add_disk_callback)
        elif event.button.id == "detail_remove_disk":
            enabled_disks = [d['path'] for d in self.vm_info.get("disks", []) if d['status'] == 'enabled']
            if not enabled_disks:
                self.app.show_error_message("No enabled disks to remove.")
                return

            def remove_disk_callback(disk_to_remove):
                if disk_to_remove:
                    try:
                        remove_disk(self.domain, disk_to_remove)
                        self.app.show_success_message(f"Disk {disk_to_remove} removed.")
                        self._update_disk_list()
                    except Exception as e:
                        self.app.show_error_message(f"Error removing disk: {e}")
            self.app.push_screen(RemoveDiskModal(enabled_disks), remove_disk_callback)
        elif event.button.id == "detail_disable_disk":
            enabled_disks = [d['path'] for d in self.vm_info.get("disks", []) if d['status'] == 'enabled']
            if not enabled_disks:
                self.app.show_error_message("No enabled disks to disable.")
                return

            def disable_disk_callback(disk_to_disable):
                if disk_to_disable:
                    try:
                        disable_disk(self.domain, disk_to_disable)
                        self.app.show_success_message(f"Disk {disk_to_disable} disabled.")
                        self._update_disk_list()
                    except (libvirt.libvirtError, ValueError, Exception) as e:
                        self.app.show_error_message(f"Error disabling disk: {e}")

            self.app.push_screen(SelectDiskModal(enabled_disks, "Select disk to disable"), disable_disk_callback)
        elif event.button.id == "detail_enable_disk":
            disabled_disks = [d['path'] for d in self.vm_info.get("disks", []) if d['status'] == 'disabled']
            if not disabled_disks:
                self.app.show_error_message("No disabled disks to enable.")
                return

            def enable_disk_callback(disk_to_enable):
                if disk_to_enable:
                    try:
                        enable_disk(self.domain, disk_to_enable)
                        self.app.show_success_message(f"Disk {disk_to_enable} enabled.")
                        self._update_disk_list()
                    except (libvirt.libvirtError, ValueError, Exception) as e:
                        self.app.show_error_message(f"Error enabling disk: {e}")
            
            self.app.push_screen(SelectDiskModal(disabled_disks, "Select disk to enable"), enable_disk_callback)

        elif event.button.id == "edit-cpu":
            def edit_cpu_callback(new_cpu_count):
                if new_cpu_count is not None and new_cpu_count.isdigit():
                    try:
                        set_vcpu(self.domain, int(new_cpu_count))
                        self.app.show_success_message(f"CPU count set to {new_cpu_count}")
                        self.query_one("#cpu-label").update(f"CPU: {new_cpu_count}")
                        self.vm_info['cpu'] = int(new_cpu_count)
                    except (libvirt.libvirtError, Exception) as e:
                        self.app.show_error_message(f"Error setting CPU: {e}")

            self.app.push_screen(EditCpuModal(current_cpu=str(self.vm_info.get('cpu', ''))), edit_cpu_callback)

        elif event.button.id == "edit-memory":
            def edit_memory_callback(new_memory_size):
                if new_memory_size is not None and new_memory_size.isdigit():
                    try:
                        set_memory(self.domain, int(new_memory_size))
                        self.app.show_success_message(f"Memory size set to {new_memory_size} MB")
                        self.query_one("#memory-label").update(f"Memory: {new_memory_size} MB")
                        self.vm_info['memory'] = int(new_memory_size)
                    except (libvirt.libvirtError, Exception) as e:
                        self.app.show_error_message(f"Error setting memory: {e}")

            self.app.push_screen(EditMemoryModal(current_memory=str(self.vm_info.get('memory', ''))), edit_memory_callback)

        elif event.button.id == "edit-machine-type":
            machine_types = get_supported_machine_types(self.domain.connect(), self.domain)
            if not machine_types:
                self.app.show_error_message("Could not retrieve machine types.")
                return

            def set_machine_type_callback(new_type):
                if new_type:
                    try:
                        set_machine_type(self.domain, new_type)
                        self.app.show_success_message(f"Machine type set to {new_type}")
                        self.query_one("#machine-type-label").update(f"Machine Type: {new_type}")
                        self.vm_info['machine_type'] = new_type
                    except (libvirt.libvirtError, Exception) as e:
                        self.app.show_error_message(f"Error setting machine type: {e}")

            self.app.push_screen(SelectMachineTypeModal(machine_types, current_machine_type=self.vm_info.get('machine_type', '')), set_machine_type_callback)

        elif event.button.id == "change-network-button":
            logging.info(f"Attempting to change network for VM: {self.vm_name}")
            try:
                available_networks_info = list_networks(self.app.conn)
                available_networks = [net['name'] for net in available_networks_info]

                vm_xml = self.domain.XMLDesc(0)
                vm_interfaces = get_vm_networks_info(vm_xml)

                if not vm_interfaces:
                    self.app.show_error_message(f"No network interfaces found for VM {self.vm_name}.")
                    return

                def handle_change_network(result: dict | None):
                    if result:
                        mac = result['mac_address']
                        new_net = result['new_network']
                        try:
                            change_vm_network(self.domain, mac, new_net)
                            self.app.show_success_message(f"Network for interface {mac} changed to {new_net}.")
                            self.dismiss() # Dismiss the current modal to force a refresh on the parent
                        except Exception as e:
                            logging.error(traceback.format_exc())
                            self.app.show_error_message(f"Error changing network: {e}")

                self.app.push_screen(ChangeNetworkDialog(vm_interfaces, available_networks), handle_change_network)

            except Exception as e:
                self.app.show_error_message(f"Error preparing to change network: {e}")

    def action_close_modal(self) -> None:
        """Close the modal."""
        self.dismiss()

class NetworkXMLModal(BaseModal[None]):
    """Modal screen to show detailed network information."""

    def __init__(self, network_name: str, network_xml: str) -> None:
        super().__init__()
        self.network_name = network_name
        self.network_xml = network_xml

    def compose(self) -> ComposeResult:
        with Vertical(id="network-detail-dialog"):
            yield Label(f"Network Details: {self.network_name}", id="title")
            with ScrollableContainer():
                text_area = TextArea(self.network_xml, language="xml", read_only=True)
                text_area.styles.height = "auto"
                yield text_area
            with Horizontal():
                yield Button("Close", variant="default", id="close-btn", classes="close-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-btn":
            self.dismiss(None)

class VirshShellScreen(ModalScreen):
    """Screen for an interactive virsh shell."""

    BINDINGS = [
        ("escape", "app.pop_screen", "Close Shell"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="virsh-shell-container"):
            yield Header()
            yield Label("Virsh Interactive Shell (esc to quit)", id="virsh-shell-title")
            yield TextArea(
                id="virsh-output",
                read_only=True,
                show_line_numbers=False,
                classes="virsh-output-area"
            )
            with Horizontal(id="virsh-input-container"):
                #yield Label("virsh>")
                yield Input(
                    placeholder="Enter virsh command...",
                    id="virsh-command-input",
                    classes="virsh-input-field"
                )
            yield Footer()

    async def on_mount(self) -> None:
        self.virsh_process = None
        self.output_textarea = self.query_one("#virsh-output", TextArea)
        self.command_input = self.query_one("#virsh-command-input", Input)

        starting_virsh_text = "Starting virsh shell..."
        self.app.show_success_message(starting_virsh_text)

        try:
            # We need to connect to the current libvirt URI
            uri = self.app.connection_uri if hasattr(self.app, 'connection_uri') else "qemu:///system"
            
            self.virsh_process = await asyncio.create_subprocess_exec(
                "/usr/bin/virsh", "-c", uri,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            self.output_textarea.text += f"Connected to: {uri}\n"

            self.read_stdout_task = asyncio.create_task(self._read_stream(self.virsh_process.stdout))
            self.read_stderr_task = asyncio.create_task(self._read_stream(self.virsh_process.stderr))

            self.command_input.focus()

        except FileNotFoundError:
            error_msg = "Error: 'virsh' command not found. Please ensure libvirt-client is installed."
            self.app.show_error_message(error_msg)
            self.command_input.disabled = True
        except Exception as e:
            error_msg = f"Error starting virsh: {e}"
            self.app.show_error_message(error_msg)
            self.command_input.disabled = True

    async def _read_stream(self, stream: asyncio.StreamReader) -> None:
        while True:
            try:
                line = await stream.readline()
                if not line:
                    break
                self.output_textarea.text += line.decode().strip() + "\n"
            except asyncio.CancelledError:
                break
            except Exception as e:
                reading_err_msg = f"Error reading from virsh: {e}"
                self.app.show_error_message(reading_err_msg)
                break

    @on(Input.Submitted, "#virsh-command-input")
    async def on_command_input_submitted(self, event: Input.Submitted) -> None:
        command = event.value.strip()
        self.command_input.value = ""
        if not command:
            return

        self.output_textarea.text += f"virsh> {command}\n"

        if self.virsh_process and self.virsh_process.stdin:
            try:
                self.virsh_process.stdin.write(command.encode() + b"\n")
                await self.virsh_process.stdin.drain()
            except Exception as e:
                error_msg = f"Error sending command: {e}"
                self.app.show_error_message(error_msg)
        else:
            error_msg = "Virsh process not running."
            self.app.show_error_message(error_msg)

        # Scroll to the end after writing output
        self.output_textarea.scroll_end()

    async def on_unmount(self) -> None:
        if self.read_stdout_task:
            self.read_stdout_task.cancel()
            await self.read_stdout_task
        if self.read_stderr_task:
            self.read_stderr_task.cancel()
            await self.read_stderr_task
        
        if self.virsh_process and self.virsh_process.returncode is None:
            self.virsh_process.terminate()
            await self.virsh_process.wait()
            tmsg = "Virsh shell terminated.\n"
            self.app.show_success_message(tmsg)

class VMManagerTUI(App):
    """A Textual application to manage VMs."""

    BINDINGS = [
        ("v", "view_log", "Log"),
        ("ctrl+v", "virsh_shell", "Virsh Shell"),
        ("f", "filter_view", "Filter"),
        ("s", "select_server", "Select Server"),
        ("p", "server_preferences", "Server Pref"),
        ("m", "manage_server", "Servers List"),
        ("q", "quit", "Quit"),
    ]

    config = load_config()
    servers = config.get('servers', [])

    @staticmethod
    def _get_initial_connection_uri(servers_list):
        if servers_list:
            return servers_list[0]['uri']
        return "qemu:///system"

    connection_uri = reactive(_get_initial_connection_uri(servers))
    conn = None
    current_page = reactive(0)
    VMS_PER_PAGE = config.get('VMS_PER_PAGE', 4)
    sort_by = reactive("default")
    search_text = reactive("")
    num_pages = reactive(1)

    CSS_PATH = ["tui.css", "vmcard.css", "dialog.css"]

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        with Horizontal(classes="top-controls"):
            yield Button("Server Pref", id="server_preferences_button", classes="Buttonpage")
            yield Button("Servers List", id="manage_servers_button", classes="Buttonpage")
            #yield Button("Create VM", id="create_vm_button", classes="Buttonpage")
            yield Button("Select Server", id="select_server_button", classes="Buttonpage")
            yield Button("Filter VM", id="filter_button", classes="Buttonpage")
            #yield Button("Virsh Shell", id="virsh_shell_button", classes="Buttonpage")
            yield Button("View Log", id="view_log_button", classes="Buttonpage")
            yield Link("About", url="https://github.com/aginies/vmanager")

        with Horizontal(id="pagination-controls") as pc:
            pc.styles.display = "none"
            pc.styles.align_horizontal = "center"
            pc.styles.height = "auto"
            pc.styles.padding_bottom = 0
            yield Button("Previous Page", id="prev-button", variant="primary", classes="ctrlpage")
            yield Label("", id="page-info", classes="")
            yield Button("Next Page", id="next-button", variant="primary", classes="ctrlpage")

        #with ScrollableContainer(id="vms-container"):
        with Vertical(id="vms-container"):
            pass # VMCard will be directly mounted here

        yield Static(id="error-footer", classes="error-message")
        yield Footer()

    def reload_servers(self, new_servers):
        self.servers = new_servers
        self.config['servers'] = new_servers
        save_config(self.config)

    def on_mount(self) -> None:
        """Called when the app is mounted."""
        self.title = "Rainbow V Manager"
        error_footer = self.query_one("#error-footer")
        error_footer.styles.height = 0
        error_footer.styles.overflow = "hidden"
        error_footer.styles.padding = 0
        vms_container = self.query_one("#vms-container")
        vms_container.styles.grid_size_columns = 2
        #self._update_vms_container_layout()
        if not self.servers:
            self.query_one("#select_server_button", Button).display = False
            self.show_success_message("No servers configured. Please add one via 'Servers List' or 'Select Server' (Custom URL).")
        else:
            self.connect_libvirt(self.connection_uri)
            self.update_header()
            self.list_vms()

    def _update_vms_container_layout(self) -> None:
        """Update the VM cards container layout based on terminal size."""
        vms_container = self.query_one("#vms-container")
        width = self.size.width

        # Define breakpoints for column count
        if width < 47:
            vms_container.styles.grid_size_columns = 1
        elif width < 88:
            vms_container.styles.grid_size_columns = 2
        elif width < 120:
            vms_container.styles.grid_size_columns = 3
        else:
            vms_container.styles.grid_size_columns = 4

    #def on_resize(self, event) -> None:
    #    """Called when the terminal is resized."""
    #    self._update_vms_container_layout()

    def on_unload(self) -> None:
        """Called when the app is about to be unloaded."""
        if self.conn:
            self.conn.close()

    def connect_libvirt(self, uri: str) -> None:
        """Connects to libvirt."""
        if self.conn:
            try:
                self.conn.close()
            except libvirt.libvirtError:
                pass  # Ignore errors when closing old connection

        try:
            self.conn = libvirt.open(uri)
            if self.conn is None:
                self.show_error_message(f"Failed to connect to {uri}")
            else:
                self.connection_uri = uri
        except libvirt.libvirtError as e:
            self.show_error_message(f"Connection error: {e}")
            self.conn = None

    def show_error_message(self, message: str):
        # Log the error to file
        logging.error(message)
        self.notify(message, severity="error", timeout=10, title="Error!")

    def show_success_message(self, message: str):
        # Log the success to file
        logging.info(message)
        self.notify(message, timeout=10, title="Info")

    @on(Button.Pressed, "#filter_button")
    def action_filter_view(self) -> None:
        """Filter the VM list."""
        self.push_screen(FilterModal(current_search=self.search_text, current_status=self.sort_by), self.handle_filter_result)

    def handle_filter_result(self, result: dict | None) -> None:
        """Handle the result from the filter modal."""
        if result:
            new_status = result.get('status', 'default')
            new_search = result.get('search', '')

            logging.info(f"Filter changed to status={new_status}, search='{new_search}'")

            status_changed = self.sort_by != new_status
            search_changed = self.search_text != new_search

            if status_changed or search_changed:
                self.sort_by = new_status
                self.search_text = new_search
                self.current_page = 0
                self.refresh_vm_list()

    @on(Button.Pressed, "#select_server_button")
    def action_select_server(self) -> None:
        """Select a server to connect to."""
        if self.servers:
            self.push_screen(ServerSelectionModal(self.servers), self.handle_server_selection_result)

    def handle_server_selection_result(self, uri: str | None) -> None:
        """Handle the result from the server selection modal."""
        if uri:
            logging.info(f"Server selected: {uri}")
            self.change_connection(uri)

    @on(Button.Pressed, "#manage_servers_button")
    def action_manage_server(self) -> None:
        """Manage the list of servers."""
        self.push_screen(ServerManagementModal(self.servers), self.reload_servers)

    @on(Button.Pressed, "#create_vm_button")
    def on_create_vm_button_pressed(self, event: Button.Pressed) -> None:
        logging.info("Create VM button clicked")
        self.push_screen(CreateVMModal(), self.handle_create_vm_result)

    @on(Button.Pressed, "#view_log_button")
    def action_view_log(self) -> None:
        """View the application log file."""
        log_file = "vm_manager.log"
        self.push_screen(LogModal(), self.handle_log_result)

    @on(Button.Pressed, "#server_preferences_button")
    def action_server_preferences(self) -> None:
        """Show server preferences modal."""
        self.push_screen(ServerPrefModal())

    @on(Button.Pressed, "#virsh_shell_button")
    def action_virsh_shell(self) -> None:
        """Show the virsh shell modal."""
        self.push_screen(VirshShellScreen())

    @on(VMNameClicked)
    async def on_vm_name_clicked(self, message: VMNameClicked) -> None:
        logging.info(f"VM name clicked: {message.vm_name}")
        if not self.conn:
            return

        try:
            domain = self.conn.lookupByName(message.vm_name)
            info = domain.info()
            xml_content = domain.XMLDesc(0)
            vm_info = {
                'name': domain.name(),
                'uuid': domain.UUIDString(),
                'status': get_status(domain),
                'description': get_vm_description(domain),
                'cpu': info[3],
                'memory': info[2] // 1024,  # Convert KiB to MiB
                'machine_type': get_vm_machine_info(xml_content),
                'firmware': get_vm_firmware_info(xml_content),
                'shared_memory': get_vm_shared_memory_info(xml_content),
                'networks': get_vm_networks_info(xml_content),
                'detail_network': get_vm_network_ip(domain),
                'network_dns_gateway': get_vm_network_dns_gateway_info(domain),
                'disks': get_vm_disks_info(xml_content),
                'devices': get_vm_devices_info(xml_content),
                'xml': xml_content,
            }
            def on_detail_modal_dismissed(result: None): # Result is None for VMDetailModal
                self.refresh_vm_list()

            self.push_screen(VMDetailModal(message.vm_name, vm_info, domain), on_detail_modal_dismissed)
        except libvirt.libvirtError as e:
            self.show_error_message(f"Error getting details for {message.vm_name}: {e}")


    def handle_log_result(self, result: str | None) -> None:
        """Handle the result from the log view."""
        if result:
            logging.info("Log View")

    def handle_create_vm_result(self, result: dict | None) -> None:
        """Handle the result from the CreateVMModal and create the VM."""
        if result:
            vm_name = result.get('name')
            memory = int(result.get('memory', 0))
            vcpu = int(result.get('vcpu', 0))
            disk_path = result.get('disk')

            if not all([vm_name, memory, vcpu, disk_path]):
                self.show_error_message("Missing VM details for creation.")
                return

            if not self.conn:
                self.show_error_message("Not connected to libvirt. Cannot create VM.")
                return

            xml = f"""
<domain type='kvm'>
  <name>{vm_name}</name>
  <memory unit='MiB'>{memory}</memory>
  <currentMemory unit='MiB'>{memory}</currentMemory>
  <vcpu placement='static'>{vcpu}</vcpu>
  etc...
"""
            try:
                self.conn.defineXML(xml)
                self.show_success_message(f"VM '{vm_name}' created successfully.")
                self.refresh_vm_list()
            except libvirt.libvirtError as e:
                self.show_error_message(f"Error creating VM '{vm_name}': {e}")


    def change_connection(self, uri: str) -> None:
        """Change the connection URI and refresh the VM list."""
        logging.info(f"Changing connection to {uri}")
        if not uri or uri.strip() == "":
            return

        self.current_page = 0
        self.connect_libvirt(uri)
        self.refresh_vm_list()


    def refresh_vm_list(self) -> None:
        """Refreshes the list of VMs."""
        vms_container = self.query_one("#vms-container")
        vms_container.remove_children()
        self.list_vms()
        self.update_header()

    def update_header(self):
        if not self.conn:
            self.show_error_message(f"Failed to open connection to {self.connection_uri}")
            return

        try:
            running_vms = 0
            stopped_vms = 0
            paused_vms = 0
            domains = self.conn.listAllDomains(0)
            if domains is not None:
                for domain in domains:
                    state = domain.info()[0]
                    if state == libvirt.VIR_DOMAIN_RUNNING:
                        running_vms += 1
                    elif state == libvirt.VIR_DOMAIN_PAUSED:
                        paused_vms += 1
                    else:
                        stopped_vms += 1

            total_vms = len(domains) if domains is not None else 0

            # Get the server name from the config
            server_name = "Unknown"
            if not self.servers:
                server_name = f"Default: {self.connection_uri}"
            else:
                for server in self.servers:
                    if server['uri'] == self.connection_uri:
                        server_name = server['name']
                        break

            self.sub_title = f"Server: {server_name} | Total VMs: {total_vms}"
        except libvirt.libvirtError:
            self.show_error_message("Connection lost")
            self.conn = None

    def list_vms(self):
        vms_container = self.query_one("#vms-container")
        if not self.conn:
            return

        try:
            all_domains = self.conn.listAllDomains(0) or []
            total_vms_unfiltered = len(all_domains)

            domains_to_display = all_domains
            if self.sort_by != "default":
                if self.sort_by == "running":
                    domains_to_display = [
                        d
                        for d in all_domains
                        if d.info()[0] == libvirt.VIR_DOMAIN_RUNNING
                    ]
                elif self.sort_by == "paused":
                    domains_to_display = [
                        d
                        for d in all_domains
                        if d.info()[0] == libvirt.VIR_DOMAIN_PAUSED
                    ]
                elif self.sort_by == "stopped":
                    domains_to_display = [
                        d
                        for d in all_domains
                        if d.info()[0]
                        not in [
                            libvirt.VIR_DOMAIN_RUNNING,
                            libvirt.VIR_DOMAIN_PAUSED,
                        ]
                    ]

            if self.search_text:
                domains_to_display = [
                    d for d in domains_to_display if self.search_text.lower() in d.name().lower()
                ]

            total_filtered_vms = len(domains_to_display)
            self.update_pagination_controls(total_filtered_vms, total_vms_unfiltered)

            start_index = self.current_page * self.VMS_PER_PAGE
            end_index = start_index + self.VMS_PER_PAGE
            paginated_domains = domains_to_display[start_index:end_index]

            for domain in paginated_domains:
                info = domain.info()
                vm_card = VMCard()
                vm_card.name = domain.name()
                vm_card.status = get_status(domain)
                vm_card.cpu = info[3]
                vm_card.memory = info[1] // 1024
                vm_card.vm = domain
                vm_card.color = "#323232"
                vms_container.mount(vm_card)
        except libvirt.libvirtError:
            self.show_error_message("Connection lost")
            self.conn = None

    def update_pagination_controls(self, total_filtered_vms: int, total_vms_unfiltered: int):
        pagination_controls = self.query_one("#pagination-controls")
        if total_vms_unfiltered <= self.VMS_PER_PAGE:
            pagination_controls.styles.display = "none"
            return
        else:
            pagination_controls.styles.display = "block"

        num_pages = (total_filtered_vms + self.VMS_PER_PAGE - 1) // self.VMS_PER_PAGE
        self.num_pages = num_pages

        page_info = self.query_one("#page-info", Label)
        page_info.update(f" [ {self.current_page + 1}/{num_pages} ]")

        prev_button = self.query_one("#prev-button", Button)
        prev_button.disabled = self.current_page == 0

        next_button = self.query_one("#next-button", Button)
        next_button.disabled = self.current_page >= num_pages - 1

    @on(Button.Pressed, "#prev-button")
    def action_previous_page(self) -> None:
        """Go to the previous page."""
        if self.current_page > 0:
            self.current_page -= 1
            self.refresh_vm_list()

    @on(Button.Pressed, "#next-button")
    def action_next_page(self) -> None:
        """Go to the next page."""
        if self.current_page < self.num_pages - 1:
            self.current_page += 1
            self.refresh_vm_list()

    async def action_quit(self) -> None:
        """Quit the application."""
        self.exit()

if __name__ == "__main__":
    terminal_size = os.get_terminal_size()
    if terminal_size.lines < 34:
        print(f"Terminal height is too small ({terminal_size.lines} lines). Please resize to at least 34 lines.")
        sys.exit(1)
    if terminal_size.columns < 92:
        print(f"Terminal width is too small ({terminal_size.columns} columns). Please resize to at least 92 columns.")
        sys.exit(1)

    app = VMManagerTUI()
    app.run()
