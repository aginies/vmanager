"""
Server pref modal
Main interface
"""

import libvirt
from textual.app import ComposeResult
from textual import on
from textual.containers import ScrollableContainer, Horizontal, Vertical
from textual.widgets import (
        Button, Label,
        DataTable, Static,
        TabbedContent, TabPane, Tree
        )
from modals.base_modals import BaseModal
from modals.network_modals import CreateNetworkModal, NetworkXMLModal
from modals.disk_pool_modals import (
        AddPoolModal,
        CreateVolumeModal,
        )
from modals.utils_modals import ConfirmationDialog

from vm_queries import (
      get_all_vm_nvram_usage, get_all_vm_disk_usage,
      get_all_network_usage
      )
from network_manager import (
      list_networks, get_vms_using_network, delete_network,
      set_network_active, set_network_autostart
      )
import storage_manager


class ServerPrefModal(BaseModal[None]):
    """Modal screen for server preferences."""

    def __init__(self, uri: str | None = None) -> None:
        super().__init__()
        self.uri = uri

    def compose(self) -> ComposeResult:
        with Vertical(id="server-pref-dialog", classes="ServerPrefModal"):
            yield Label("Server Preferences", id="server-pref-title")
            yield Static(classes="button-separator")
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
        uri_to_connect = self.uri
        if uri_to_connect is None:
            if len(self.app.active_uris) == 0:
                self.app.show_error_message("Not connected to any server.")
                self.dismiss()
                return
            if len(self.app.active_uris) > 1:
                # This should not happen if the app logic uses the server selection modal
                self.app.show_error_message("Multiple servers active but none selected for preferences.")
                self.dismiss()
                return
            uri_to_connect = self.app.active_uris[0]

        self.conn = self.app.connection_manager.connect(uri_to_connect)
        if not self.conn:
            self.app.show_error_message(f"Failed to get connection for server preferences on {uri_to_connect}.")
            self.dismiss()
            return

        # Get server hostname and update the title
        server_hostname = self.conn.getHostname()
        self.query_one("#server-pref-title", Label).update(f"Server Preferences ({server_hostname})")

        self._load_networks()
        disk_map = get_all_vm_disk_usage(self.conn)
        nvram_map = get_all_vm_nvram_usage(self.conn)
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
        pools = storage_manager.list_storage_pools(self.conn)
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

        network_usage = get_all_network_usage(self.conn)
        self.networks_list = list_networks(self.conn)

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

        is_pool = bool(node_data and node_data.get("type") == "pool")
        is_volume = bool(node_data and node_data.get("type") == "volume")

        toggle_active_btn = self.query_one("#toggle-active-pool-btn")
        toggle_autostart_btn = self.query_one("#toggle-autostart-pool-btn")
        del_pool_btn = self.query_one("#del-pool-btn")
        add_pool_btn = self.query_one("#add-pool-btn")

        toggle_active_btn.display = is_pool
        toggle_autostart_btn.display = is_pool
        del_pool_btn.display = is_pool
        add_pool_btn.display = is_pool

        self.query_one("#del-vol-btn").display = is_volume
        self.query_one("#add-vol-btn").display = is_pool

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
                    self.app.show_success_message(f"Volume '{result['name']}' '{result['size_gb']}' '{result['format']}' created successfully.")
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

        self.app.push_screen(AddPoolModal(self.conn), on_create)

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
                ConfirmationDialog(f"Are you sure you want to delete storage pool:\n' {pool_name}'\nThis will delete the pool definition but not the data on it."), on_confirm)

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
                set_network_active(self.conn, net_name, not net_info['active'])
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
                set_network_autostart(self.conn, net_name, not net_info['autostart'])
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
                conn = self.conn
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
            vms_using_network = get_vms_using_network(self.conn, network_name)

            confirm_message = f"Are you sure you want to delete network:\n'{network_name}'"
            if vms_using_network:
                vm_list = ", ".join(vms_using_network)
                confirm_message += f"\nThis network is currently in use by the following VMs:\n{vm_list}."

            def on_confirm(confirmed: bool) -> None:
                if confirmed:
                    try:
                        delete_network(self.conn, network_name)
                        self.app.show_success_message(f"Network '{network_name}' deleted successfully.")
                        self._load_networks()
                    except Exception as e:
                        self.app.show_error_message(f"Error deleting network '{network_name}': {e}")

            self.app.push_screen(
                ConfirmationDialog(confirm_message), on_confirm
            )
