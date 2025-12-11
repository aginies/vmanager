"""
Main interface
"""
import os
import sys
import logging
import asyncio
import traceback
from collections import namedtuple

from textual.app import App, ComposeResult
from textual.widgets import (
        DirectoryTree, Header, Footer, Select, Button, Input, Label, Static,
        DataTable, Link, TextArea, ListView, ListItem, Checkbox, RadioButton,
        RadioSet, TabbedContent, TabPane, Tree
        )
from textual.containers import ScrollableContainer, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual import on
import libvirt
from libvirt_error_handler import register_error_handler
from vmcard import VMCard, VMNameClicked, ConfirmationDialog, ChangeNetworkDialog
from vm_queries import (
    get_status, get_vm_description, get_vm_machine_info, get_vm_firmware_info,
    get_vm_networks_info, get_vm_network_ip, get_vm_network_dns_gateway_info,
    get_vm_disks_info, get_vm_devices_info, get_vm_shared_memory_info,
    get_supported_machine_types, get_boot_info, get_vm_video_model,
    get_cpu_models, get_vm_cpu_model, get_vm_sound_model, get_vm_graphics_info,
    get_all_vm_nvram_usage, get_all_vm_disk_usage, get_all_network_usage
)
from vm_actions import (
    add_disk, remove_disk, set_vcpu, set_memory, set_machine_type, enable_disk,
    disable_disk, change_vm_network, set_shared_memory, remove_virtiofs,
    add_virtiofs, set_vm_video_model, set_cpu_model, set_uefi_file,
    set_vm_graphics
)
from network_manager import (
    list_networks, delete_network, get_vms_using_network,
    set_network_active, set_network_autostart
)
from firmware_manager import (
    get_uefi_files, get_host_sev_capabilities
)
import storage_manager
from config import load_config, save_config

from modals.base_modal import BaseModal
from modals.connection_modals import ServerSelectionModal
from modals.network_modals import CreateNetworkModal, NetworkXMLModal
from modals.log_modal import LogModal
from modals.server_modals import ServerManagementModal
from modals.disk_pool_modals import (
        SelectPoolModal, AddDiskModal,AddPoolModal,
        CreateVolumeModal
        )

# Configure logging
logging.basicConfig(
    filename='vm_manager.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


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


class EditCpuModal(BaseModal[str | None]):
    """Modal screen for editing VCPU count."""

    def __init__(self, current_cpu: str = "") -> None:
        super().__init__()
        self.current_cpu = current_cpu

    def compose(self) -> ComposeResult:
        with Vertical(id="edit-cpu-dialog", classes="edit-cpu-dialog"):
            yield Label("Enter new VCPU count")
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
        with Vertical(id="edit-memory-dialog", classes="edit-memory-dialog"):
            yield Label("Enter new memory size (MB)")
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
        with Vertical(id="select-machine-type-dialog", classes="select-machine-type-dialog"):
            yield Label("Select Machine Type:")
            with ScrollableContainer():
                yield ListView(
                    *[ListItem(Label(mt)) for mt in self.machine_types],
                    id="machine-type-list",
                    classes="machine-type-list"
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

    def on_mount(self) -> None:
        self.query_one(DirectoryTree).focus()

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        self._selected_path = event.path
        self.query_one("#select-btn").disabled = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "select-btn":
            if self._selected_path:
                self.dismiss(str(self._selected_path))
        elif event.button.id == "cancel-btn":
            self.dismiss(None)

class ServerPrefModal(BaseModal[None]):
    """Modal screen for server preferences."""

    def compose(self) -> ComposeResult:
        with Vertical(id="server-pref-dialog", classes="ServerPrefModal"):
            yield Label("Server Preferences", id="server-pref-title")
            with TabbedContent(id="server-pref-tabs"):
                with TabPane("Network", id="tab-network"):
                    with ScrollableContainer():
                        yield DataTable(id="networks-table", classes="networks-table", cursor_type="row")
                    with Vertical(classes="small"):
                        with Horizontal():
                            yield Button("Toggle Active", id="toggle-net-active-btn", classes="toggle-detail-button", variant="primary", disabled=True)
                            yield Button("Toggle Autostart", id="toggle-net-autostart-btn", classes="toggle-detail-button", variant="primary", disabled=True)
                        with Horizontal():
                            yield Button("Add", id="add-net-btn", variant="success", classes="toggle-detail-button")
                            yield Button("View", id="view-net-btn", variant="success", classes="toggle-detail-button", disabled=True)
                            yield Button("Delete", id="delete-net-btn", variant="error", classes="toggle-detail-button", disabled=True)
                        yield Button("Close", id="close-btn", classes="close-button")
                with TabPane("Storage", id="tab-storage"):
                    with ScrollableContainer(classes="storage-pool-details"):
                        yield Tree("Storage Pools", id="storage-tree")
                    with Vertical(id="storage-actions", classes="button-details"):
                        with Horizontal():
                            yield Button(id="toggle-active-pool-btn", variant="primary", classes="toggle-detail-button")
                            yield Button(id="toggle-autostart-pool-btn", variant="primary", classes="toggle-detail-button")
                            yield Button("Add Pool", id="add-pool-btn", variant="success", classes="toggle-detail-button")
                            yield Button("Delete Pool", id="del-pool-btn", variant="error", classes="toggle-detail-button")
                            yield Button("New Volume", id="add-vol-btn", variant="success", classes="toggle-detail-button")
                            yield Button("Delete Volume", id="del-vol-btn", variant="error", classes="toggle-detail-button")

    def on_mount(self) -> None:
        self._load_networks()
        disk_map = get_all_vm_disk_usage(self.app.conn)
        nvram_map = get_all_vm_nvram_usage(self.app.conn)
        self.file_to_vm_map = {**disk_map, **nvram_map}
        self._load_storage_pools()

        self.query_one("#toggle-active-pool-btn").display = False
        self.query_one("#toggle-autostart-pool-btn").display = False
        self.query_one("#add-pool-btn").display = False
        self.query_one("#del-pool-btn").display = False
        self.query_one("#add-vol-btn").display = False
        self.query_one("#del-vol-btn").display = False


    def _load_storage_pools(self) -> None:
        """Load storage pools into the tree view."""
        tree: Tree[dict] = self.query_one("#storage-tree")
        tree.clear()
        tree.root.data = {"type": "root"}
        pools = storage_manager.list_storage_pools(self.app.conn)
        for pool_data in pools:
            pool_name = pool_data['name']
            status = pool_data['status']
            autostart = "autostart" if pool_data['autostart'] else "no autostart"
            label = f"{pool_name} [{status}, {autostart}]"
            pool_node = tree.root.add(label, data=pool_data)
            pool_node.data["type"] = "pool"
            # Add a dummy node to make the pool node expandable
            pool_node.add_leaf("Loading volumes...")

    def _load_networks(self):
        table = self.query_one("#networks-table", DataTable)

        if not table.columns:
            table.add_column("Name", key="name")
            table.add_column("Mode", key="mode")
            table.add_column("Active", key="active")
            table.add_column("Autostart", key="autostart")
            table.add_column("Used By", key="used_by")

        table.clear()

        network_usage = get_all_network_usage(self.app.conn)
        self.networks_list = list_networks(self.app.conn)

        for net in self.networks_list:
            vms_str = ", ".join(network_usage.get(net['name'], [])) or "Not in use"
            active_str = "✔️" if net['active'] else "❌"
            autostart_str = "✔️" if net['autostart'] else "❌"

            table.add_row(
                net['name'],
                net['mode'],
                active_str,
                autostart_str,
                vms_str,
                key=net['name']
            )

    @on(Tree.NodeExpanded)
    async def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        """Load child nodes when a node is expanded."""
        node = event.node
        node_data = node.data
        if not node_data or node_data.get("type") != "pool":
            return

        # If it's the first time expanding, the only child is the dummy "Loading..."
        if len(node.children) == 1 and node.children[0].data is None:
            node.remove_children()
            pool = node_data.get('pool')
            if pool and pool.isActive():
                volumes = storage_manager.list_storage_volumes(pool)
                for vol_data in volumes:
                    vol_name = vol_data['name']
                    vol_path = vol_data['volume'].path()
                    capacity_gb = round(vol_data['capacity'] / (1024**3), 2)

                    vm_name = self.file_to_vm_map.get(vol_path)
                    usage_info = f" (in use by {vm_name})" if vm_name else ""

                    label = f"{vol_name} ({capacity_gb} GB){usage_info}"
                    child_node = node.add(label, data=vol_data)
                    child_node.data["type"] = "volume"
                    child_node.allow_expand = False
            else:
                # Handle case where pool is not active
                node.add_leaf("Pool is not active")


    @on(Tree.NodeSelected)
    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Handle node selection to enable/disable buttons."""
        node = event.node
        node_data = node.data if node else None

        is_pool = node_data and node_data.get("type") == "pool"
        is_volume = node_data and node_data.get("type") == "volume"

        toggle_active_btn = self.query_one("#toggle-active-pool-btn")
        toggle_autostart_btn = self.query_one("#toggle-autostart-pool-btn")
        del_pool_btn = self.query_one("#del-pool-btn")
        add_pool_btn = self.query_one("#add-pool-btn")

        toggle_active_btn.display = is_pool
        toggle_autostart_btn.display = is_pool
        del_pool_btn.display = is_pool
        add_pool_btn.display = is_pool

        self.query_one("#del-vol-btn").display = is_volume
        self.query_one("#add-vol-btn").display = is_volume or is_pool

        if is_pool:
            is_active = node_data.get('status') == 'active'
            has_autostart = node_data.get('autostart', False)
            toggle_active_btn.label = "Deactivate" if is_active else "Activate"
            toggle_autostart_btn.label = "Autostart Off" if has_autostart else "Autostart On"

    @on(Button.Pressed, "#toggle-active-pool-btn")
    def on_toggle_active_pool_button_pressed(self, event: Button.Pressed) -> None:
        """Handle pool activation/deactivation."""
        tree: Tree[dict] = self.query_one("#storage-tree")
        if not tree.cursor_node or not tree.cursor_node.data:
            return

        node_data = tree.cursor_node.data
        if node_data.get("type") != "pool":
            return

        pool = node_data.get('pool')
        is_active = node_data.get('status') == 'active'
        try:
            storage_manager.set_pool_active(pool, not is_active)
            self.app.show_success_message(f"Pool '{pool.name()}' is now {'inactive' if is_active else 'active'}.")
            self._load_storage_pools() # Refresh the tree
        except Exception as e:
            self.app.show_error_message(str(e))

    @on(Button.Pressed, "#toggle-autostart-pool-btn")
    def on_toggle_autostart_pool_button_pressed(self, event: Button.Pressed) -> None:
        """Handle pool autostart toggling."""
        tree: Tree[dict] = self.query_one("#storage-tree")
        if not tree.cursor_node or not tree.cursor_node.data:
            return

        node_data = tree.cursor_node.data
        if node_data.get("type") != "pool":
            return

        pool = node_data.get('pool')
        has_autostart = node_data.get('autostart', False)
        try:
            storage_manager.set_pool_autostart(pool, not has_autostart)
            self.app.show_success_message(f"Autostart for pool '{pool.name()}' is now {'off' if has_autostart else 'on'}.")
            self._load_storage_pools() # Refresh the tree
        except Exception as e:
            self.app.show_error_message(str(e))

    @on(Button.Pressed, "#add-vol-btn")
    def on_add_volume_button_pressed(self, event: Button.Pressed) -> None:
        tree: Tree[dict] = self.query_one("#storage-tree")
        if not tree.cursor_node or not tree.cursor_node.data:
            return

        node_data = tree.cursor_node.data
        if node_data.get("type") != "pool":
            return

        pool = node_data.get('pool')

        def on_create(result: dict | None) -> None:
            if result:
                try:
                    storage_manager.create_volume(
                        pool,
                        result['name'],
                        result['size_gb'],
                        result['format']
                    )
                    self.app.show_success_message(f"Volume '{result['name']}' created successfully.")
                    # Refresh the node
                    if tree.cursor_node:
                        tree.cursor_node.remove_children()
                        tree.cursor_node.add_leaf("Loading volumes...")
                        self.app.call_later(tree.cursor_node.expand)

                except Exception as e:
                    self.app.show_error_message(str(e))

        self.app.push_screen(CreateVolumeModal(), on_create)

    @on(Button.Pressed, "#add-pool-btn")
    def on_add_pool_button_pressed(self, event: Button.Pressed) -> None:
        def on_create(success: bool | None) -> None:
            if success:
                self._load_storage_pools()

        self.app.push_screen(AddPoolModal(), on_create)

    @on(Button.Pressed, "#del-pool-btn")
    def on_delete_pool_button_pressed(self, event: Button.Pressed) -> None:
        tree: Tree[dict] = self.query_one("#storage-tree")
        if not tree.cursor_node or not tree.cursor_node.data:
            return

        node_data = tree.cursor_node.data
        if node_data.get("type") != "pool":
            return

        pool_name = node_data.get('name')
        pool = node_data.get('pool')

        def on_confirm(confirmed: bool) -> None:
            if confirmed:
                try:
                    storage_manager.delete_storage_pool(pool)
                    self.app.show_success_message(f"Storage pool '{pool_name}' deleted successfully.")
                    self._load_storage_pools() # Refresh the tree
                except Exception as e:
                    self.app.show_error_message(str(e))

        self.app.push_screen(
                ConfirmationDialog(f"Are you sure you want to delete storage pool:\n'{pool_name}'\nThis will delete the pool definition but not the data on it."),
            on_confirm
        )

    @on(Button.Pressed, "#del-vol-btn")
    def on_delete_volume_button_pressed(self, event: Button.Pressed) -> None:
        tree: Tree[dict] = self.query_one("#storage-tree")
        if not tree.cursor_node or not tree.cursor_node.data:
            return

        node_data = tree.cursor_node.data
        if node_data.get("type") != "volume":
            return

        vol_name = node_data.get('name')
        vol = node_data.get('volume')

        def on_confirm(confirmed: bool) -> None:
            if confirmed:
                try:
                    storage_manager.delete_volume(vol)
                    self.app.show_success_message(f"Volume '{vol_name}' deleted successfully.")
                    # Refresh the parent node
                    parent_node = tree.cursor_node.parent
                    tree.cursor_node.remove()
                    if parent_node and not parent_node.children:
                        parent_node.add_leaf("No volumes")

                except Exception as e:
                    self.app.show_error_message(str(e))

        self.app.push_screen(
                ConfirmationDialog(f"Are you sure you want to delete volume:\n'{vol_name}'"),
            on_confirm
        )


    @on(DataTable.RowSelected, "#networks-table")
    def on_network_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.query_one("#view-net-btn").disabled = False
        self.query_one("#delete-net-btn").disabled = False

        toggle_active_btn = self.query_one("#toggle-net-active-btn")
        toggle_autostart_btn = self.query_one("#toggle-net-autostart-btn")
        toggle_active_btn.disabled = False
        toggle_autostart_btn.disabled = False

        selected_net_name = event.row_key.value
        net_info = next((net for net in self.networks_list if net['name'] == selected_net_name), None)
        if net_info:
            toggle_active_btn.label = "Deactivate" if net_info['active'] else "Activate"
            toggle_autostart_btn.label = "Autostart Off" if net_info['autostart'] else "Autostart On"

    @on(Button.Pressed, "#toggle-net-active-btn")
    def on_toggle_net_active_pressed(self, event: Button.Pressed) -> None:
        table = self.query_one("#networks-table", DataTable)
        if not table.cursor_coordinate: return

        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        net_name = row_key.value
        net_info = next((net for net in self.networks_list if net['name'] == net_name), None)

        if net_info:
            try:
                set_network_active(self.app.conn, net_name, not net_info['active'])
                self.app.show_success_message(f"Network '{net_name}' is now {'inactive' if net_info['active'] else 'active'}.")
                self._load_networks()
            except Exception as e:
                self.app.show_error_message(str(e))

    @on(Button.Pressed, "#toggle-net-autostart-btn")
    def on_toggle_net_autostart_pressed(self, event: Button.Pressed) -> None:
        table = self.query_one("#networks-table", DataTable)
        if not table.cursor_coordinate: return

        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        net_name = row_key.value
        net_info = next((net for net in self.networks_list if net['name'] == net_name), None)

        if net_info:
            try:
                set_network_autostart(self.app.conn, net_name, not net_info['autostart'])
                self.app.show_success_message(f"Autostart for network '{net_name}' is now {'off' if net_info['autostart'] else 'on'}.")
                self._load_networks()
            except Exception as e:
                self.app.show_error_message(str(e))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-btn":
            self.dismiss(None)
        elif event.button.id == "view-net-btn":
            table = self.query_one("#networks-table", DataTable)
            if not table.cursor_coordinate:
                return

            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
            network_name = row_key.value
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
            self.app.push_screen(CreateNetworkModal(), on_create)
        elif event.button.id == "delete-net-btn":
            table = self.query_one("#networks-table", DataTable)
            if not table.cursor_coordinate:
                return

            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
            network_name = row_key.value
            vms_using_network = get_vms_using_network(self.app.conn, network_name)

            confirm_message = f"Are you sure you want to delete network:\n'{network_name}'"
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



BootDevice = namedtuple("BootDevice", ["type", "id", "description", "boot_order_idx"])

class VMDetailModal(ModalScreen):
    """Modal screen to show detailed VM information."""

    BINDINGS = [("escape", "close_modal", "Close")]

    boot_order: reactive(list)
    all_bootable_devices: reactive(list)
    graphics_info: reactive(dict) # New reactive variable

    def __init__(self, vm_name: str, vm_info: dict, domain: libvirt.virDomain) -> None:
        super().__init__()
        self.vm_name = vm_name
        self.vm_info = vm_info
        self.domain = domain
        self.available_networks = []
        self.selected_virtiofs_target = None
        self.selected_virtiofs_info = None # Store full info for editing
        self.boot_order = self.vm_info.get('boot', {}).get('order', [])
        self.all_bootable_devices = [] # Initialize the new reactive list
        self.sev_caps = {'sev': False, 'sev-es': False}
        self.uefi_path_map = {}
        self.graphics_info = get_vm_graphics_info(self.domain.XMLDesc(0)) # Initialize here


    def on_mount(self) -> None:
        try:
            all_networks_info = list_networks(self.app.conn)
            self.available_networks = [net['name'] for net in all_networks_info]
        except (libvirt.libvirtError, Exception) as e:
            self.app.show_error_message(f"Could not load networks: {e}")
            self.available_networks = []
        self.query_one("#detail2-vm").add_class("hidden")

        # Populate Boot tab
        boot_menu_enabled = self.vm_info.get('boot', {}).get('menu_enabled', False)
        self.query_one("#boot-menu-enable", Checkbox).value = boot_menu_enabled

        # SEV capabilities
        firmware_type = self.vm_info['firmware'].get('type', 'BIOS')

        if firmware_type == 'UEFI':
            try:
                self.sev_caps = get_host_sev_capabilities(self.domain.connect())
                sev_checkbox = self.query_one("#sev-checkbox", Checkbox)
                sev_es_checkbox = self.query_one("#sev-es-checkbox", Checkbox)
                sev_checkbox.display = self.sev_caps['sev']
                sev_es_checkbox.display = self.sev_caps['sev-es']
                sev_checkbox.disabled = not self.vm_info.get("status") == "Stopped"
                sev_es_checkbox.disabled = not self.vm_info.get("status") == "Stopped"
            except Exception as e:
                self.app.show_error_message(f"Could not get SEV capabilities: {e}")
                try:
                    self.query_one("#sev-checkbox", Checkbox).display = False
                    self.query_one("#sev-es-checkbox", Checkbox).display = False
                except Exception:
                    pass

            self._update_uefi_options()
        
        # Initialize Graphics tab values
        self._update_graphics_ui()

    def _get_bootable_devices(self) -> list[BootDevice]:
        """Gathers all disks and network interfaces as bootable devices."""
        devices = []
        # Add disks
        for disk in self.vm_info.get("disks", []):
            path = disk.get('path')
            if path:
                boot_order_idx = None
                try:
                    boot_order_idx = self.boot_order.index(path) + 1
                except ValueError:
                    pass # Not in boot order

                devices.append(BootDevice(
                    type="Disk",
                    id=path,
                    description=os.path.basename(path),
                    boot_order_idx=boot_order_idx
                ))

        # Add network interfaces
        for net in self.vm_info.get("networks", []):
            mac = net.get('mac')
            if mac:
                boot_order_idx = None
                try:
                    boot_order_idx = self.boot_order.index(mac) + 1
                except ValueError:
                    pass # Not in boot order
                devices.append(BootDevice(
                    type="NIC",
                    id=mac,
                    description=f"MAC: {mac} ({net.get('network', 'N/A')})",
                    boot_order_idx=boot_order_idx
                ))
        return devices

    def _update_graphics_ui(self) -> None:
        """Updates the UI elements for the Graphics tab based on self.graphics_info."""
        is_stopped = self.vm_info.get("status") == "Stopped"

        try:
            graphics_type_select = self.query_one("#graphics-type-select", Select)
            graphics_type_select.value = self.graphics_info['type']
            graphics_type_select.disabled = not is_stopped
        except Exception:
            pass

        try:
            listen_type_select = self.query_one("#graphics-listen-type-select", Select)
            listen_type_select.value = self.graphics_info['listen_type']
            listen_type_select.disabled = not is_stopped
        except Exception:
            pass

        try:
            address_radioset = self.query_one("#graphics-address-radioset", RadioSet)
            if self.graphics_info['listen_type'] == 'none':
                 address_radioset.disabled = True
            elif self.graphics_info['address'] == '127.0.0.1':
                address_radioset.set_pressed("graphics-address-localhost")
                address_radioset.disabled = not is_stopped
            elif self.graphics_info['address'] == '0.0.0.0':
                address_radioset.set_pressed("graphics-address-all")
                address_radioset.disabled = not is_stopped
            else:
                address_radioset.set_pressed("graphics-address-default")
                address_radioset.disabled = not is_stopped
            
        except Exception:
            pass

        try:
            port_input = self.query_one("#graphics-port-input", Input)
            port_input.value = str(self.graphics_info['port']) if self.graphics_info['port'] else ""
            port_input.disabled = not is_stopped or self.graphics_info['autoport']
        except Exception:
            pass

        try:
            autoport_checkbox = self.query_one("#graphics-autoport-checkbox", Checkbox)
            autoport_checkbox.value = self.graphics_info['autoport']
            autoport_checkbox.disabled = not is_stopped
        except Exception:
            pass

        try:
            password_enable_checkbox = self.query_one("#graphics-password-enable-checkbox", Checkbox)
            password_enable_checkbox.value = self.graphics_info['password_enabled']
            password_enable_checkbox.disabled = not is_stopped
        except Exception:
            pass

        try:
            password_input = self.query_one("#graphics-password-input", Input)
            password_input.value = self.graphics_info['password'] if self.graphics_info['password_enabled'] else ""
            password_input.disabled = not is_stopped or not self.graphics_info['password_enabled']
        except Exception:
            pass

        try:
            self.query_one("#graphics-apply-btn", Button).disabled = not is_stopped
        except Exception:
            pass

    def _update_uefi_options(self) -> None:
        """Filters and updates the UEFI file selection list."""
        try:
            uefi_select = self.query_one("#uefi-file-select", Select)
        except Exception: # QueryError means the Firmware tab might not be UEFI type
            return

        all_uefi_files = get_uefi_files()
        uefi_files_to_show = all_uefi_files

        try:
            secure_boot_on = self.query_one("#secure-boot-checkbox", Checkbox).value
            if secure_boot_on:
                uefi_files_to_show = [f for f in uefi_files_to_show if 'secure-boot' in f.features]
        except Exception: # QueryError
            pass

        try:
            sev_checkbox = self.query_one("#sev-checkbox", Checkbox)
            if sev_checkbox.display and sev_checkbox.value:
                uefi_files_to_show = [f for f in uefi_files_to_show if 'amd-sev' in f.features]
        except Exception: # QueryError
            pass

        try:
            sev_es_checkbox = self.query_one("#sev-es-checkbox", Checkbox)
            if sev_es_checkbox.display and sev_es_checkbox.value:
                uefi_files_to_show = [f for f in uefi_files_to_show if 'sev-es' in f.features]
        except Exception: # QueryError
            pass

        current_path = self.vm_info['firmware'].get('path')
        current_basename = os.path.basename(current_path) if current_path else None

        self.uefi_path_map = {os.path.basename(f.executable): f.executable for f in uefi_files_to_show if f.executable}

        if current_basename and current_basename not in self.uefi_path_map:
            self.uefi_path_map[current_basename] = current_path

        uefi_options = [(basename, basename) for basename in sorted(self.uefi_path_map.keys())]
        uefi_select.set_options(uefi_options)

        if current_basename and any(opt[1] == current_basename for opt in uefi_options):
            uefi_select.value = current_basename

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

    @on(Select.Changed, "#cpu-model-select")
    def on_cpu_model_changed(self, event: Select.Changed) -> None:
        new_cpu_model = event.value
        original_cpu_model = self.vm_info.get('cpu_model', 'default')

        if new_cpu_model == original_cpu_model:
            return

        try:
            set_cpu_model(self.domain, new_cpu_model)
            self.app.show_success_message(f"CPU model set to {new_cpu_model}")
            self.vm_info['cpu_model'] = new_cpu_model
            self.query_one("#cpu-model-label").update(f"CPU Model: {new_cpu_model}")
        except (libvirt.libvirtError, ValueError, Exception) as e:
            self.app.show_error_message(f"Error setting CPU model: {e}")
            event.control.value = original_cpu_model

    @on(Select.Changed, "#uefi-file-select")
    def on_uefi_file_changed(self, event: Select.Changed) -> None:
        new_uefi_basename = event.value
        new_uefi_path = self.uefi_path_map.get(new_uefi_basename)
        original_uefi_path = self.vm_info['firmware'].get('path')
        current_secure_boot = self.query_one("#secure-boot-checkbox", Checkbox).value

        if new_uefi_path == original_uefi_path:
            return

        try:
            set_uefi_file(self.domain, new_uefi_path, current_secure_boot)
            if new_uefi_path:
                self.app.show_success_message(f"UEFI file set to {os.path.basename(new_uefi_path)}")
                self.query_one("#firmware-path-label").update(f"File: {os.path.basename(new_uefi_path)}")
            else:
                self.app.show_success_message("Firmware set to BIOS.")
                self.query_one("#firmware-path-label").update("File: ")
            self.vm_info['firmware']['path'] = new_uefi_path
        except (libvirt.libvirtError, ValueError, Exception) as e:
            self.app.show_error_message(f"Error setting UEFI file: {e}")
            original_basename = os.path.basename(original_uefi_path) if original_uefi_path else None
            if original_basename and original_basename in self.uefi_path_map:
                event.control.value = original_basename
            else:
                event.control.clear()

    @on(Select.Changed, "#video-model-select")
    def on_video_model_changed(self, event: Select.Changed) -> None:
        new_model = event.value
        current_model = self.vm_info.get('video_model') or "default"

        if new_model == current_model:
            return

        try:
            set_vm_video_model(self.domain, new_model if new_model != "default" else None)
            self.app.show_success_message(f"Video model set to {new_model}")
            self.query_one("#video-model-label").update(f"Video Model: {new_model}")
            self.vm_info['video_model'] = new_model if new_model != "default" else None
        except (libvirt.libvirtError, Exception) as e:
            self.app.show_error_message(f"Error setting video model: {e}")
            # Revert selection
            event.control.value = current_model

    @on(Checkbox.Changed, "#secure-boot-checkbox")
    def on_secure_boot_checkbox_changed(self, event: Checkbox.Changed) -> None:
        self._update_uefi_options()

        current_uefi_path = self.vm_info['firmware'].get('path')
        if not current_uefi_path and event.value: # Trying to enable secure boot without a UEFI file
            self.app.show_error_message("Cannot enable secure boot without a UEFI file selected.")
            event.checkbox.value = not event.value # Revert checkbox
            self._update_uefi_options() # Revert options
            return

        try:
            set_uefi_file(self.domain, current_uefi_path, event.value)
            self.app.show_success_message(f"Secure Boot {'enabled' if event.value else 'disabled'}.")
            self.vm_info['firmware']['secure_boot'] = event.value
        except (libvirt.libvirtError, ValueError, Exception) as e:
            self.app.show_error_message(f"Error setting Secure Boot: {e}")
            event.checkbox.value = not event.value # Revert checkbox
            self._update_uefi_options() # Revert options

    @on(Checkbox.Changed, "#sev-checkbox, #sev-es-checkbox")
    def on_sev_checkbox_changed(self, event: Checkbox.Changed) -> None:
        self._update_uefi_options()

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

    # --- Graphics Tab Event Handlers ---
    @on(Select.Changed, "#graphics-type-select")
    def on_graphics_type_changed(self, event: Select.Changed) -> None:
        self.graphics_info['type'] = event.value
        self._update_graphics_ui()

    @on(Select.Changed, "#graphics-listen-type-select")
    def on_graphics_listen_type_changed(self, event: Select.Changed) -> None:
        self.graphics_info['listen_type'] = event.value
        # If listen type changes to none, clear address
        if event.value == 'none':
            self.graphics_info['address'] = ''
        self._update_graphics_ui()

    @on(RadioSet.Changed, "#graphics-address-radioset")
    def on_graphics_address_changed(self, event: RadioSet.Changed) -> None:
        if event.pressed.id == "graphics-address-localhost":
            self.graphics_info['address'] = '127.0.0.1'
        elif event.pressed.id == "graphics-address-all":
            self.graphics_info['address'] = '0.0.0.0'
        else:
            # For "Hypervisor default", we'll send "0.0.0.0" as a generic default
            # but libvirt might interpret this differently depending on its config.
            # In the UI, it means "don't specify a particular address string".
            self.graphics_info['address'] = '0.0.0.0'
        self._update_graphics_ui()

    @on(Checkbox.Changed, "#graphics-autoport-checkbox")
    def on_graphics_autoport_changed(self, event: Checkbox.Changed) -> None:
        self.graphics_info['autoport'] = event.value
        self._update_graphics_ui()

    @on(Checkbox.Changed, "#graphics-password-enable-checkbox")
    def on_graphics_password_enable_changed(self, event: Checkbox.Changed) -> None:
        self.graphics_info['password_enabled'] = event.value
        self._update_graphics_ui()

    @on(Input.Changed, "#graphics-port-input")
    def on_graphics_port_input_changed(self, event: Input.Changed) -> None:
        try:
            self.graphics_info['port'] = int(event.value) if event.value else None
        except ValueError:
            self.graphics_info['port'] = None # Invalid input, treat as None
        # No UI update needed here, as it's just updating internal state

    @on(Input.Changed, "#graphics-password-input")
    def on_graphics_password_input_changed(self, event: Input.Changed) -> None:
        self.graphics_info['password'] = event.value
        # No UI update needed here, as it's just updating internal state

    @on(Button.Pressed, "#graphics-apply-btn")
    def on_graphics_apply_button_pressed(self, event: Button.Pressed) -> None:
        if self.vm_info.get("status") != "Stopped":
            self.app.show_error_message("VM must be stopped to apply graphics settings.")
            return

        graphics_type = self.query_one("#graphics-type-select", Select).value
        listen_type = self.query_one("#graphics-listen-type-select", Select).value
        
        # Determine address
        address = None # Default for 'none' listen type
        if listen_type == 'address':
            address_radioset = self.query_one("#graphics-address-radioset", RadioSet)
            if address_radioset.pressed_button.id == "graphics-address-localhost":
                address = "127.0.0.1"
            elif address_radioset.pressed_button.id == "graphics-address-all":
                address = "0.0.0.0"
            else: # Hypervisor default, which can be expressed as 0.0.0.0 in libvirt or omitted
                address = "0.0.0.0"

        autoport = self.query_one("#graphics-autoport-checkbox", Checkbox).value
        port_input = self.query_one("#graphics-port-input", Input)
        port = int(port_input.value) if port_input.value and not autoport else None

        password_enabled = self.query_one("#graphics-password-enable-checkbox", Checkbox).value
        password_input = self.query_one("#graphics-password-input", Input)
        password = password_input.value if password_enabled else None

        try:
            set_vm_graphics(
                self.domain,
                graphics_type if graphics_type != "" else None, # Convert "None" string back to None
                listen_type,
                address,
                port,
                autoport,
                password_enabled,
                password
            )
            self.app.show_success_message("Graphics settings applied successfully.")
            # Refresh graphics_info after successful application
            self.graphics_info = get_vm_graphics_info(self.domain.XMLDesc(0))
            self._update_graphics_ui()
        except libvirt.libvirtError as e:
            self.app.show_error_message(f"Error applying graphics settings: {e}")
        except Exception as e:
            self.app.show_error_message(f"An unexpected error occurred: {e}")

    def compose(self) -> ComposeResult:
        with Vertical(id="vm-detail-container"):
            yield Label(f"VM Details: {self.vm_name}", id="title")
            yield Label(f"UUID: {self.vm_info.get('uuid', 'N/A')}")
            status = self.vm_info.get("status", "N/A")
            yield Label(f"Status: {status}", id=f"status-{status.lower().replace(' ', '-')}", classes="centered-status-label")
            yield Button("Toggle Tab Content", id="toggle-detail-button", classes="toggle-detail-button")
            with TabbedContent(id="detail-vm"):
                with TabPane("CPU", id="detail-cpu-tab"):
                    is_stopped = self.vm_info.get("status") == "Stopped"
                    with Vertical(classes="info-details"):
                        yield Label(f"CPU: {self.vm_info.get('cpu', 'N/A')}", id="cpu-label", classes="tabd")
                        yield Button("Edit", id="edit-cpu", classes="edit-detail-btn")

                        # CPU Model Selection
                        current_cpu_model = self.vm_info.get('cpu_model', 'default')
                        yield Label(f"CPU Model: {current_cpu_model}", id="cpu-model-label", classes="tabd")

                        import xml.etree.ElementTree as ET
                        xml_root = ET.fromstring(self.vm_info['xml'])
                        arch_elem = xml_root.find(".//os/type")
                        arch = arch_elem.get('arch') if arch_elem is not None else 'x86_64'

                        cpu_models = get_cpu_models(self.domain.connect(), arch)
                        # Ensure 'host-passthrough' and 'default' are in the list
                        if 'host-passthrough' not in cpu_models:
                            cpu_models.append('host-passthrough')
                        if 'default' not in cpu_models:
                            cpu_models.append('default')

                        cpu_model_options = [(model, model) for model in sorted(cpu_models)]

                        yield Select(
                            cpu_model_options,
                            value=current_cpu_model,
                            id="cpu-model-select",
                            disabled=not is_stopped,
                            classes="cpu-model-select"
                        )
                with TabPane("Mem", id="detail-mem-tab", ):
                    with Vertical(classes="info-details"):
                        yield Label(f"Memory: {self.vm_info.get('memory', 'N/A')} MB", id="memory-label", classes="tabd")
                        yield Button("Edit", id="edit-memory", classes="edit-detail-btn")
                        is_stopped = self.vm_info.get("status") == "Stopped"
                        yield Checkbox("Shared Memory", value=self.vm_info.get('shared_memory', False), id="shared-memory-checkbox", classes="shared-memory", disabled=not is_stopped)
                with TabPane("Firmware", id="detail-firmware-tab"):
                    with Vertical(classes="info-details"):
                        is_stopped = self.vm_info.get("status") == "Stopped"
                        firmware_info = self.vm_info.get('firmware', {'type': 'BIOS'})

                        firmware_type = firmware_info.get('type', 'BIOS')
                        firmware_path = firmware_info.get('path')

                        yield Label(f"Firmware: {firmware_type}", id="firmware-type-label")
                        if firmware_path:
                            yield Label(f"File: {os.path.basename(firmware_path)}", id="firmware-path-label")

                        if firmware_type == 'UEFI':
                            yield Checkbox(
                                "Secure Boot",
                                value=firmware_info.get('secure_boot', False),
                                id="secure-boot-checkbox",
                                disabled=not is_stopped,
                            )
                            yield Checkbox("AMD-SEV", id="sev-checkbox", disabled=not is_stopped)
                            yield Checkbox("AMD-SEV-ES", id="sev-es-checkbox", disabled=not is_stopped)

                            yield Select(
                                [], # Will be populated in on_mount
                                id="uefi-file-select",
                                disabled=not is_stopped,
                                allow_blank=True,
                            )

                        if "machine_type" in self.vm_info:
                            yield Label(f"Machine Type: {self.vm_info['machine_type']}", id="machine-type-label", classes="tabd")
                            yield Button("Edit", id="edit-machine-type", classes="edit-detail-btn", disabled=not is_stopped)

                with TabPane("Boot", id="detail-boot-tab"):
                    is_stopped = self.vm_info.get("status") == "Stopped"
                    with Vertical(classes="info-details"):
                        yield Checkbox("Enable boot menu", id="boot-menu-enable", disabled=not is_stopped)
                        #yield Label("Boot Devices:", classes="boot_order_label")
                        #yield DataTable(id="boot-devices-table")

                with TabPane("Disks", id="detail-disk-tab"):
                    with ScrollableContainer(classes="info-details"):
                        disks_info = self.vm_info.get("disks", [])
                        disk_items = []
                        if disks_info:
                            for disk in disks_info:
                                path = disk.get('path', 'N/A')
                                status = disk.get('status', 'unknown')
                                label = f"{path}"
                                if status == 'disabled':
                                    label += " (disabled)"
                                disk_items.append(ListItem(Label(label)))
                        else:
                            disk_items.append(ListItem(Label("No disks found.")))

                        self.disk_list_view = ListView(*disk_items)
                        num_disks = len(disks_info)
                        self.disk_list_view.styles.height = num_disks if num_disks > 0 else 1
                        yield self.disk_list_view

                    has_enabled_disks = any(d['status'] == 'enabled' for d in disks_info)
                    has_disabled_disks = any(d['status'] == 'disabled' for d in disks_info)
                    remove_button = Button("Remove Disk", id="detail_remove_disk", classes="detail-disks")
                    disable_button = Button("Disable Disk", id="detail_disable_disk", classes="detail-disks")
                    enable_button = Button("Enable Disk", id="detail_enable_disk", classes="detail-disks")
                    remove_button.display = has_enabled_disks
                    disable_button.display = has_enabled_disks
                    enable_button.display = has_disabled_disks

                    with Vertical(classes="button-details"):
                        with Horizontal():
                            yield Button("Add Disk", id="detail_add_disk", classes="detail-disks")
                            yield Button("Attach Existing Disk", id="detail_attach_disk", classes="detail-disks")
                            yield remove_button
                            with Vertical():
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
                        with Vertical(classes="button-details"):
                            with Horizontal():
                                yield Button("Add", variant="primary", id="add-virtiofs-btn", classes="detail-disks")
                                yield Button("Edit", variant="default", id="edit-virtiofs-btn", disabled=True, classes="detail-disks")
                                yield Button("Delete", variant="error", id="delete-virtiofs-btn", disabled=True, classes="detail-disks")

                with TabPane("Video", id="detail-video-tab"):
                    with Vertical(classes="info-details"):
                        current_model = self.vm_info.get('video_model') or "default"
                        is_stopped = self.vm_info.get("status") == "Stopped"
                        video_models = ["default", "virtio", "qxl", "vga", "cirrus", "bochs", "ramfb", "none"]
                        video_model_options = [(model, model) for model in video_models]

                        yield Label(f"Video Model: {current_model}", id="video-model-label")
                        yield Select(
                            video_model_options,
                            value=current_model if current_model in video_models else "default",
                            id="video-model-select",
                            disabled=not is_stopped,
                            allow_blank=False,
                        )

                with TabPane("Graphics", id="detail-graphics-tab"):
                    is_stopped = self.vm_info.get("status") == "Stopped"
                    with ScrollableContainer(): #classes="info-details"):
                        yield Label("Type:")
                        yield Select(
                            [("VNC", "vnc"), ("Spice", "spice"), ("None", "")],
                            value=self.graphics_info['type'],
                            id="graphics-type-select",
                            disabled=not is_stopped
                        )
                        yield Label("Listen Type:")
                        yield Select(
                            [("Address", "address"), ("None", "none")],
                            value=self.graphics_info['listen_type'],
                            id="graphics-listen-type-select",
                            disabled=not is_stopped
                        )
                        yield Label("Address:")
                        with RadioSet(id="graphics-address-radioset", disabled=not is_stopped or self.graphics_info['listen_type'] != 'address'):
                            yield RadioButton("Hypervisor default", id="graphics-address-default", value=self.graphics_info['address'] not in ['127.0.0.1', '0.0.0.0'])
                            yield RadioButton("Localhost only", id="graphics-address-localhost", value=self.graphics_info['address'] == '127.0.0.1')
                            yield RadioButton("All interfaces", id="graphics-address-all", value=self.graphics_info['address'] == '0.0.0.0')
                        yield Checkbox(
                            "Auto Port",
                            value=self.graphics_info['autoport'],
                            id="graphics-autoport-checkbox",
                            disabled=not is_stopped
                        )
                        yield Input(
                            placeholder="Port (e.g., 5900)",
                            value=str(self.graphics_info['port']) if self.graphics_info['port'] else "",
                            id="graphics-port-input",
                            type="integer",
                            disabled=not is_stopped or self.graphics_info['autoport']
                        )
                        yield Checkbox(
                            "Enable Password",
                            value=self.graphics_info['password_enabled'],
                            id="graphics-password-enable-checkbox",
                            disabled=not is_stopped
                        )
                        yield Input(
                            placeholder="Password",
                            value=self.graphics_info['password'] if self.graphics_info['password_enabled'] else "",
                            id="graphics-password-input",
                            password=True, # Hide password input
                            disabled=not is_stopped or not self.graphics_info['password_enabled']
                        )
                        yield Button("Apply Graphics Settings", id="graphics-apply-btn", variant="primary", disabled=not is_stopped)
 
            with TabbedContent(id="detail2-vm"):
        # TOFIX !
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

            yield Button("Close", variant="default", id="close-btn", classes="close-button")

    def _update_disk_list(self):
        self.disk_list_view.clear()
        new_xml = self.domain.XMLDesc(0)
        disks_info = get_vm_disks_info(self.app.conn, new_xml)
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

    def on_button_pressed(self, event: Button.Pressed) -> None:

        if event.button.id == "toggle-detail-button":
            vm = self.query_one("#detail-vm")
            vm2 = self.query_one("#detail2-vm")
            vm.toggle_class("hidden")
            vm2.toggle_class("hidden")
        elif event.button.id == "close-btn":
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
                message = f"Are you sure you want to delete VirtIO-FS mount:\n'{self.selected_virtiofs_target}'?\nVM must be stopped!"
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
        elif event.button.id == "detail_attach_disk":
            all_pools = storage_manager.list_storage_pools(self.app.conn)
            active_pools = [p for p in all_pools if p['status'] == 'active']

            if not active_pools:
                self.app.show_error_message("No active storage pools found.")
                return

            def select_pool_callback(pool_name: str | None) -> None:
                if not pool_name:
                    return

                selected_pool_obj = next((p['pool'] for p in active_pools if p['name'] == pool_name), None)
                if not selected_pool_obj:
                    self.app.show_error_message(f"Could not find pool object for {pool_name}")
                    return

                all_volumes_in_pool = storage_manager.list_storage_volumes(selected_pool_obj)
                all_volume_paths = [vol['volume'].path() for vol in all_volumes_in_pool]

                used_disks = get_all_vm_disk_usage(self.app.conn)
                used_nvrams = get_all_vm_nvram_usage(self.app.conn)
                used_paths = set(used_disks.keys()) | set(used_nvrams.keys())

                available_disks = [path for path in all_volume_paths if path not in used_paths]

                if not available_disks:
                    self.app.show_error_message(f"No available disks found in pool '{pool_name}'.")
                    return

                def attach_disk_callback(disk_to_attach: str | None) -> None:
                    if disk_to_attach:
                        try:
                            target_dev = add_disk(
                                self.domain,
                                disk_to_attach,
                                device_type="disk",
                            )
                            self.app.show_success_message(f"Disk added as {target_dev}")
                            self._update_disk_list()
                        except Exception as e:
                            self.app.show_error_message(f"Error attaching disk: {e}")

                self.app.push_screen(
                    SelectDiskModal(available_disks, f"Select a disk to attach from pool '{pool_name}'"),
                    attach_disk_callback
                )

            self.app.push_screen(
                SelectPoolModal([p['name'] for p in active_pools], "Select a storage pool"),
                select_pool_callback
            )
        elif event.button.id == "detail_remove_disk":
            highlighted_index = self.disk_list_view.index
            if highlighted_index is None:
                self.app.show_error_message("No disk selected.")
                return

            disks_info = self.vm_info.get("disks", [])
            if highlighted_index >= len(disks_info):
                self.app.show_error_message("Invalid selection.")
                return

            disk_to_remove = disks_info[highlighted_index]
            if disk_to_remove['status'] != 'enabled':
                self.app.show_error_message("Can only remove enabled disks.")
                return

            disk_path = disk_to_remove['path']

            def on_confirm(confirmed: bool):
                if confirmed:
                    try:
                        remove_disk(self.domain, disk_path)
                        self.app.show_success_message(f"Disk {disk_path} removed.")
                        self._update_disk_list()
                    except Exception as e:
                        self.app.show_error_message(f"Error removing disk: {e}")

            self.app.push_screen(ConfirmationDialog(f"Are you sure you want to remove disk:\n{disk_path}"), on_confirm)

        elif event.button.id == "detail_disable_disk":
            highlighted_index = self.disk_list_view.index
            if highlighted_index is None:
                self.app.show_error_message("No disk selected.")
                return

            disks_info = self.vm_info.get("disks", [])
            if highlighted_index >= len(disks_info):
                self.app.show_error_message("Invalid selection.")
                return
            
            disk_to_disable = disks_info[highlighted_index]
            if disk_to_disable['status'] != 'enabled':
                self.app.show_error_message("Can only disable enabled disks.")
                return

            disk_path = disk_to_disable['path']

            def on_confirm(confirmed: bool):
                if confirmed:
                    try:
                        disable_disk(self.domain, disk_path)
                        self.app.show_success_message(f"Disk {disk_path} disabled.")
                        self._update_disk_list()
                    except (libvirt.libvirtError, ValueError, Exception) as e:
                        self.app.show_error_message(f"Error disabling disk: {e}")
            
            self.app.push_screen(ConfirmationDialog(f"Are you sure you want to disable disk:\n{disk_path}"), on_confirm)

        elif event.button.id == "detail_enable_disk":
            highlighted_index = self.disk_list_view.index
            if highlighted_index is None:
                self.app.show_error_message("No disk selected.")
                return

            disks_info = self.vm_info.get("disks", [])
            if highlighted_index >= len(disks_info):
                self.app.show_error_message("Invalid selection.")
                return
            
            disk_to_enable = disks_info[highlighted_index]
            if disk_to_enable['status'] != 'disabled':
                self.app.show_error_message("Can only enable disabled disks.")
                return
            
            disk_path = disk_to_enable['path']

            def on_confirm(confirmed: bool):
                if confirmed:
                    try:
                        enable_disk(self.domain, disk_path)
                        self.app.show_success_message(f"Disk {disk_path} enabled.")
                        self._update_disk_list()
                    except (libvirt.libvirtError, ValueError, Exception) as e:
                        self.app.show_error_message(f"Error enabling disk: {e}")
            
            self.app.push_screen(ConfirmationDialog(f"Are you sure you want to enable disk:\n{disk_path}?"), on_confirm)


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
    # changing that will break CSS value!
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
        register_error_handler()
        self.title = "Rainbow V Manager"
        self.sparkline_data = {}
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
                'cpu_model': get_vm_cpu_model(xml_content),
                'memory': info[2] // 1024,  # Convert KiB to MiB
                'machine_type': get_vm_machine_info(xml_content),
                'firmware': get_vm_firmware_info(xml_content),
                'shared_memory': get_vm_shared_memory_info(xml_content),
                'networks': get_vm_networks_info(xml_content),
                'detail_network': get_vm_network_ip(domain),
                'network_dns_gateway': get_vm_network_dns_gateway_info(domain),
                'disks': get_vm_disks_info(self.conn, xml_content),
                'devices': get_vm_devices_info(xml_content),
                'boot': get_boot_info(xml_content),
                'video_model': get_vm_video_model(xml_content),
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
                uuid = domain.UUIDString()
                if uuid not in self.sparkline_data:
                    self.sparkline_data[uuid] = {"cpu": [], "mem": []}

                cpu_hist = self.sparkline_data[uuid]["cpu"]
                mem_hist = self.sparkline_data[uuid]["mem"]

                vm_card = VMCard(cpu_history=cpu_hist, mem_history=mem_hist)
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
