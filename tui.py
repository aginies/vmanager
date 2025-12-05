from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Select, Button, Input, Label, Static, DataTable, Link, TextArea
from textual.containers import ScrollableContainer, Grid, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual import on
import libvirt
import logging
import subprocess
from datetime import datetime
from vmcard import VMCard, VMStateChanged, VMStartError, SnapshotError, SnapshotSuccess, VMNameClicked, VMActionError, VMActionSuccess
from vm_info import get_vm_info, get_status, get_vm_description, get_vm_machine_info, get_vm_firmware_info, get_vm_networks_info, get_vm_network_ip, get_vm_network_dns_gateway_info, get_vm_disks_info, get_vm_devices_info
from config import load_config, save_config

# Configure logging
logging.basicConfig(
    filename='vm_manager.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class ConnectionModal(ModalScreen):
    """Modal screen for entering connection URI."""

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

class AddServerModal(ModalScreen):
    """Modal screen for adding a new server."""

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

class EditServerModal(ModalScreen):
    """Modal screen for editing a server."""

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


class ErrorModal(ModalScreen):
    """A modal screen to display an error message."""

    def __init__(self, error_message: str):
        super().__init__()
        self.error_message = error_message

    def compose(self) -> ComposeResult:
        with Vertical(id="error-dialog"):
            yield Label("Error")
            yield Static(self.error_message)
            yield Button("Close", variant="primary", id="error-close-button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Dismiss the modal when the close button is pressed."""
        self.dismiss()


class SuccessModal(ModalScreen):
    """A modal screen to display a success message."""

    def __init__(self, success_message: str):
        super().__init__()
        self.success_message = success_message

    def compose(self) -> ComposeResult:
        with Vertical(id="success-dialog"):
            yield Label("Success")
            yield Static(self.success_message)
            yield Button("Close", variant="primary", id="success-close-button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Dismiss the modal when the close button is pressed."""
        self.dismiss()


class ServerSelectionModal(ModalScreen):
    """Modal screen for selecting a server."""

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
                yield Button("Select", id="select-btn", variant="primary", disabled=True, classes="Buttonpage")
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


class FilterModal(ModalScreen):
    """Modal screen for selecting a filter."""

    CSS_PATH = "tui.css"

    def compose(self) -> ComposeResult:
        with Vertical(id="filter-dialog", classes="FilterModal"):
            yield Label("Filter by Status")
            yield Button("All", id="sort_default", variant="primary", classes="Buttonpage")
            yield Button("Running", id="sort_running", classes="Buttonpage")
            yield Button("Paused", id="sort_paused", classes="Buttonpage")
            yield Button("Stopped", id="sort_stopped", classes="Buttonpage")
            yield Button("Cancel", id="cancel-btn", classes="close-button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        else:
            self.dismiss(event.button.id)


class CreateVMModal(ModalScreen):
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

    def __init__(self, servers: list) -> None:
        super().__init__()
        self.servers = servers
        self.selected_row = None

    def compose(self) -> ComposeResult:
        with Vertical(id="server-management-dialog"):
            yield Label("Server Management")
            with ScrollableContainer():
                yield DataTable(id="server-table")
            with Horizontal():
                yield Button("Add", id="add-server-btn", classes="add-button")
                yield Button("Edit", id="edit-server-btn", disabled=True, classes="edit-button")
                yield Button("Delete", id="delete-server-btn", disabled=True, variant="error", classes="delete-button")
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
            del self.servers[self.selected_row]
            self.app.config['servers'] = self.servers
            save_config(self.app.config)
            self._reload_table()
            self.selected_row = None
            self.query_one("#edit-server-btn").disabled = True
            self.query_one("#delete-server-btn").disabled = True

class LogModal(ModalScreen):
    """ Modal Screen to show Log"""
    def compose(self) -> ComposeResult:
        with Vertical(id="text-show"):
            logging.info("View log button clicked")
            yield Label("Log View", id="title")
            log_file = "vm_manager.log"
            text_area = TextArea()
            text_area.load_text(open(log_file, "r").read())
            yield text_area
        with Horizontal():
            yield Button("Cancel", variant="default", id="cancel-btn", classes="Buttonpage")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)

class VMDetailModal(ModalScreen):
    """Modal screen to show detailed VM information."""

    CSS_PATH = "tui.css"

    def __init__(self, vm_name: str, vm_info: dict) -> None:
        super().__init__()
        self.vm_name = vm_name
        self.vm_info = vm_info

    def compose(self) -> ComposeResult:
        with Vertical(id="vm-detail-container"):
            yield Label(f"VM Details: {self.vm_name}", id="title")

            status = self.vm_info.get("status", "N/A")
            yield Label("General information", classes="section-title")
            with ScrollableContainer(classes="info-details"):
                yield Label(
                    f"Status: {status}", id=f"status-{status.lower().replace(' ', '-')}"
                )
                yield Label(f"CPU: {self.vm_info.get('cpu', 'N/A')}")
                yield Label(f"Memory: {self.vm_info.get('memory', 'N/A')} MB")
                yield Label(f"UUID: {self.vm_info.get('uuid', 'N/A')}")
                if "firmware" in self.vm_info:
                    yield Label(f"Firmware: {self.vm_info['firmware']}")
                if "machine_type" in self.vm_info:
                    yield Label(f"Machine Type: {self.vm_info['machine_type']}")

            if self.vm_info.get("disks"):
                yield Label("Disks", classes="section-title")
                with ScrollableContainer(classes="info-details"):
                    for disk in self.vm_info["disks"]:
                        yield Static(f"• {disk}")

            if self.vm_info.get("networks"):
                yield Label("Networks", classes="section-title")
                with ScrollableContainer(classes="info-details"):
                    for network in self.vm_info["networks"]:
                        yield Static(f"• {network}")

                    if self.vm_info.get("detail_network"):
                        for netdata in self.vm_info["detail_network"]:
                            with Vertical(classes="info-details"):
                                yield Static(f"  Interface: {netdata.get('interface', 'N/A')} (MAC: {netdata.get('mac', 'N/A')})")
                                if netdata.get('ipv4'):
                                    for ip in netdata['ipv4']:
                                        yield Static(f"    IPv4: {ip}")
                                if netdata.get('ipv6'):
                                    for ip in netdata['ipv6']:
                                        yield Static(f"    IPv6: {ip}")

            if self.vm_info.get("network_dns_gateway"):
                yield Label("Network DNS & Gateway", classes="section-title")
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
                yield Label("Devices", classes="section-title")
                with ScrollableContainer(classes="info-details"):
                    for device_type, device_list in self.vm_info["devices"].items():
                        if device_list:
                            yield Static(f"  {device_type.replace('_', ' ').title()}:")
                            for device in device_list:
                                detail_str = ", ".join(f"{k}: {v}" for k, v in device.items())
                                yield Static(f"    • {detail_str}")

            with Horizontal(id="detail-button-container"):
                yield Button("Close", variant="default", id="close-btn", classes="close-button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-btn":
            self.dismiss()

class VMManagerTUI(App):
    """A Textual application to manage VMs."""

    BINDINGS = [
        ("ctrl+p", "next_page", "Next Page"),
        ("ctrl+n", "previous_page", "Previous Page"),
        ("v", "view_log", "View Log"),
        ("f", "filter_view", "Filter"),
        ("s", "select_server", "Select Server"),
        ("m", "manage_server", "Manage Servers"),
        ("q", "quit", "Quit"),
    ]

    config = load_config()
    servers = config.get('servers', [])
    connection_uri = reactive(servers[0]['uri'] if servers else "qemu:///system")
    conn = None
    current_page = reactive(0)
    VMS_PER_PAGE = config.get('VMS_PER_PAGE', 4)
    sort_by = reactive("default")
    num_pages = reactive(1)

    CSS_PATH = ["tui.css", "vmcard.css"]

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        with Horizontal(classes="top-controls"):
            yield Button("Connection", id="change_connection_button", classes="Buttonpage")
            yield Button("Manage Servers", id="manage_servers_button", classes="Buttonpage")
            #yield Button("Create VM", id="create_vm_button", classes="Buttonpage")
            if self.servers:
                yield Button("Select Server", id="select_server_button", classes="Buttonpage")
            yield Button("Filter", id="filter_button", classes="Buttonpage")
            yield Button("View Log", id="view_log_button", classes="Buttonpage")
            yield Link("About", url="https://github.com/aginies/vmanager")

        with Horizontal(id="pagination-controls") as pc:
            pc.styles.display = "none"
            pc.styles.align_horizontal = "center"
            pc.styles.height = "auto"
            pc.styles.padding_bottom = 0
            yield Button("Previous", id="prev-button", variant="primary", classes="ctrlpage")
            yield Label("", id="page-info", classes="ctrlpage")
            yield Button("Next", id="next-button", variant="primary", classes="ctrlpage")

        #with ScrollableContainer(id="vms-container"):
        with Vertical(id="vms-container"):
            pass # VMCard will be directly mounted here

        yield Static(id="error-footer", classes="error-message")
        yield Footer()

    def reload_servers(self, new_servers):
        self.servers = new_servers
        self.config['servers'] = new_servers
        save_config(self.config)
        # Re-compose is complex, for now we assume the app might need a restart
        # to see the button if servers are added from an empty state.
        # A better solution would be to dynamically add/remove the button.


    def on_mount(self) -> None:
        """Called when the app is mounted."""
        self.title = "Rainbow V Manager"
        error_footer = self.query_one("#error-footer")
        error_footer.styles.height = 0
        error_footer.styles.overflow = "hidden"
        error_footer.styles.padding = 0
        self._update_vms_container_layout()
        if not self.servers:
            self.query_one("#select_server_button", Button).display = False
        self.connect_libvirt(self.connection_uri)
        self.update_header()
        self.list_vms()

    def on_unload(self) -> None:
        """Called when the app is about to be unloaded."""
        if self.conn:
            self.conn.close()

    def _update_vms_container_layout(self) -> None:
        """Update the VM cards container layout based on terminal size."""
        vms_container = self.query_one("#vms-container")
        width = self.size.width
        
        # Define breakpoints for column count
        if width < 64:
            vms_container.styles.grid_size_columns = 1
        elif width < 92:
            vms_container.styles.grid_size_columns = 2
        elif width < 122:
            vms_container.styles.grid_size_columns = 3
        else:
            vms_container.styles.grid_size_columns = 4

    def on_resize(self, event) -> None:
        """Called when the terminal is resized."""
        self._update_vms_container_layout()

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
        self.push_screen(ErrorModal(message))

    def show_success_message(self, message: str):
        # Log the success to file
        logging.info(message)
        self.push_screen(SuccessModal(message))

    async def on_vm_state_changed(self, message: VMStateChanged) -> None:
        """Called when a VM's state changes."""
        self.set_timer(5, self.refresh_vm_list)
        self.set_timer(2, self.update_header)  # Revert header after 5 seconds

    def show_info_message(self, message: str):
        logging.info(message)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        error_footer = self.query_one("#error-footer", Static)
        error_footer.update(f"[{timestamp}] {message}")
        error_footer.styles.height = "auto"
        error_footer.styles.padding = (0, 1)

        def clear_info():
            error_footer.update("")
            error_footer.styles.height = 0
            error_footer.styles.padding = 0

        self.set_timer(5, clear_info)

    async def on_snapshot_error(self, message: SnapshotError) -> None:
        """Called when a snapshot operation fails."""
        self.show_error_message(f"Snapshot error for {message.vm_name}: {message.error_message}")

    async def on_snapshot_success(self, message: SnapshotSuccess) -> None:
        """Called when a snapshot operation succeeds."""
        self.show_success_message(f"Snapshot for {message.vm_name}: {message.message}")

    async def on_vm_action_error(self, message: VMActionError) -> None:
        """Called when a generic VM action fails."""
        self.show_error_message(f"Error on VM {message.vm_name} during '{message.action}': {message.error_message}")

    async def on_vm_action_success(self, message: VMActionSuccess) -> None:
        """Called when a generic VM action succeeds."""
        self.show_success_message(f"VM {message.vm_name} {message.action}: {message.message}")

    async def on_vm_start_error(self, message: VMStartError) -> None:
        """Called when a VM fails to start."""
        self.show_error_message(f"Error starting {message.vm_name}: {message.error_message}")

    @on(Button.Pressed, "#filter_button")
    def action_filter_view(self) -> None:
        """Filter the VM list."""
        logging.info("Filter button clicked")
        self.push_screen(FilterModal(), self.handle_filter_result)

    def handle_filter_result(self, result: str | None) -> None:
        """Handle the result from the filter modal."""
        if result:
            sort_key = result.replace("sort_", "")
            logging.info(f"Filter changed to {sort_key}")
            if self.sort_by != sort_key:
                self.sort_by = sort_key
                self.current_page = 0
                self.refresh_vm_list()

    @on(Button.Pressed, "#select_server_button")
    def action_select_server(self) -> None:
        """Select a server to connect to."""
        logging.info("Select server button clicked")
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
        logging.info("Manage servers button clicked")
        self.push_screen(ServerManagementModal(self.servers), self.reload_servers)

    @on(Button.Pressed, "#create_vm_button")
    def on_create_vm_button_pressed(self, event: Button.Pressed) -> None:
        logging.info("Create VM button clicked")
        self.push_screen(CreateVMModal(), self.handle_create_vm_result)

    @on(Button.Pressed, "#change_connection_button")
    def on_change_connection_button_pressed(self, event: Button.Pressed) -> None:
        logging.info("Change connection button clicked")
        self.push_screen(ConnectionModal(), self.handle_connection_result)

    @on(Button.Pressed, "#view_log_button")
    def action_view_log(self) -> None:
        """View the application log file."""
        logging.info("View log button clicked")
        log_file = "vm_manager.log"
        self.push_screen(LogModal(), self.handle_log_result)

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
                'networks': get_vm_networks_info(xml_content),
                'detail_network': get_vm_network_ip(domain),
                'network_dns_gateway': get_vm_network_dns_gateway_info(domain),
                'disks': get_vm_disks_info(xml_content),
                'devices': get_vm_devices_info(xml_content),
                'xml': xml_content,
            }
            self.push_screen(VMDetailModal(message.vm_name, vm_info))
        except libvirt.libvirtError as e:
            self.show_error_message(f"Error getting details for {message.vm_name}: {e}")


    def handle_connection_result(self, result: str | None) -> None:
        """Handle the result from the connection modal."""
        if result:
            logging.info(f"Connection URI entered: {result}")
            self.change_connection(result)

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
            domains = self.conn.listAllDomains(0)
            if domains is not None:
                if self.sort_by != "default":
                    if self.sort_by == "running":
                        domains = [
                            d
                            for d in domains
                            if d.info()[0] == libvirt.VIR_DOMAIN_RUNNING
                        ]
                    elif self.sort_by == "paused":
                        domains = [
                            d
                            for d in domains
                            if d.info()[0] == libvirt.VIR_DOMAIN_PAUSED
                        ]
                    elif self.sort_by == "stopped":
                        domains = [
                            d
                            for d in domains
                            if d.info()[0]
                            not in [
                                libvirt.VIR_DOMAIN_RUNNING,
                                libvirt.VIR_DOMAIN_PAUSED,
                            ]
                        ]

                total_vms = len(domains)
                self.update_pagination_controls(total_vms)

                start_index = self.current_page * self.VMS_PER_PAGE
                end_index = start_index + self.VMS_PER_PAGE
                paginated_domains = domains[start_index:end_index]

                for domain in paginated_domains:
                    info = domain.info()
                    vm_card = VMCard(
                        name=domain.name(),
                        status=get_status(domain),
                        cpu=info[3],
                        memory=info[1] // 1024,  # Convert KiB to MiB
                        vm=domain,
                        color="#323232",
                    )
                    vms_container.mount(vm_card)
        except libvirt.libvirtError:
            self.show_error_message("Connection lost")
            self.conn = None

    def update_pagination_controls(self, total_vms: int):
        pagination_controls = self.query_one("#pagination-controls")
        if total_vms <= self.VMS_PER_PAGE:
            pagination_controls.styles.display = "none"
            return
        else:
            pagination_controls.styles.display = "block"

        num_pages = (total_vms + self.VMS_PER_PAGE - 1) // self.VMS_PER_PAGE
        self.num_pages = num_pages

        page_info = self.query_one("#page-info", Label)
        page_info.update(f" Page {self.current_page + 1}/{num_pages} ")

        prev_button = self.query_one("#prev-button", Button)
        prev_button.disabled = self.current_page == 0

        next_button = self.query_one("#next-button", Button)
        next_button.disabled = self.current_page >= num_pages - 1

    @on(Button.Pressed, "#prev-button")
    def action_previous_page(self) -> None:
        """Go to the previous page."""
        logging.info("Previous page button clicked")
        if self.current_page > 0:
            self.current_page -= 1
            self.refresh_vm_list()

    @on(Button.Pressed, "#next-button")
    def action_next_page(self) -> None:
        """Go to the next page."""
        logging.info("Next page button clicked")
        if self.current_page < self.num_pages - 1:
            self.current_page += 1
            self.refresh_vm_list()

    def action_quit(self) -> None:
        """Quit the application."""
        self.exit()

if __name__ == "__main__":
    app = VMManagerTUI()
    app.run()
