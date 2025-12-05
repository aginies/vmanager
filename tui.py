from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Select, Button, Input, Label, Static
from textual.containers import ScrollableContainer, Grid, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual import on
import libvirt
import logging
import subprocess
from datetime import datetime
from vmcard import VMCard, VMStateChanged, VMStartError, SnapshotError, SnapshotSuccess, VMNameClicked, VMActionError
from vm_info import get_vm_info, get_status, get_vm_description, get_vm_machine_info, get_vm_firmware_info, get_vm_networks_info, get_vm_network_ip, get_vm_network_dns_gateway_info, get_vm_disks_info, get_vm_devices_info

# Configure logging
logging.basicConfig(
    filename='vm_manager_error.log',
    level=logging.ERROR,
    format='%(asctime)s - %(message)s'
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
        ("q", "quit", "Quit"),
    ]

    connection_uri = reactive("qemu:///system")
    conn = None
    current_page = reactive(0)
    VMS_PER_PAGE = 4
    sort_by = reactive("default")
    num_pages = reactive(1)

    CSS_PATH = ["tui.css", "vmcard.css"]

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        with Horizontal(classes="top-controls"):
            yield Button("Connection", id="change_connection_button", classes="Buttonpage")
            yield Button("View Log", id="view_log_button", classes="Buttonpage")
            with Vertical(classes="filter-group"):
                yield Select(
                    [
                        ("Filter: All", "sort_default"),
                        ("Filter: Running", "sort_running"),
                        ("Filter: Paused", "sort_paused"),
                        ("Filter: Stopped", "sort_stopped"),
                    ],
                    id="select",
                    prompt="Filter by status",
                    allow_blank=False,
                    classes="Button",
                )

        with Horizontal(id="pagination-controls") as pc:
            pc.styles.display = "none"
            pc.styles.align_horizontal = "center"
            pc.styles.height = "auto"
            pc.styles.padding_top = 1
            yield Button("Previous", id="prev-button", variant="primary", classes="Buttonpage")
            yield Label("", id="page-info")
            yield Button("Next", id="next-button", variant="primary", classes="Buttonpage")

        with ScrollableContainer(id="vms-container"):
            yield Grid(id="grid")

        yield Static(id="error-footer", classes="error-message")
        yield Footer()

    def on_mount(self) -> None:
        """Called when the app is mounted."""
        self.title = "VM Manager"
        error_footer = self.query_one("#error-footer")
        error_footer.styles.height = 0
        error_footer.styles.overflow = "hidden"
        error_footer.styles.padding = 0
        grid = self.query_one("#grid")
        grid.styles.grid_gutter_vertical = 1
        grid.styles.grid_gutter_horizontal = 1
        self._update_grid_layout()
        self.connect_libvirt(self.connection_uri)
        self.update_header()
        self.list_vms()

    def on_unload(self) -> None:
        """Called when the app is about to be unloaded."""
        if self.conn:
            self.conn.close()

    def _update_grid_layout(self) -> None:
        """Update the grid layout based on terminal size."""
        grid = self.query_one("#grid")
        width = self.size.width
        
        # Define breakpoints for column count
        if width < 80:
            grid.styles.grid_size_columns = 1
        elif width < 120:
            grid.styles.grid_size_columns = 2
        else:
            grid.styles.grid_size_columns = 3
    
    def on_resize(self, event) -> None:
        """Called when the terminal is resized."""
        self._update_grid_layout()

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
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        error_footer = self.query_one("#error-footer", Static)
        error_footer.update(f"[{timestamp}] {message}")
        error_footer.styles.height = "auto"
        error_footer.styles.padding = (0, 1)

        # Log the error to file
        logging.error(message)

        def clear_error():
            error_footer.update("")
            error_footer.styles.height = 0
            error_footer.styles.padding = 0

        self.set_timer(15, clear_error)

    async def on_vm_state_changed(self, message: VMStateChanged) -> None:
        """Called when a VM's state changes."""
        self.set_timer(5, self.refresh_vm_list)
        self.set_timer(2, self.update_header)  # Revert header after 5 seconds

    def show_info_message(self, message: str):
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
        self.show_info_message(f"Success for {message.vm_name}: {message.message}")

    async def on_vm_action_error(self, message: VMActionError) -> None:
        """Called when a generic VM action fails."""
        self.show_error_message(f"Error on VM {message.vm_name} during '{message.action}': {message.error_message}")

    async def on_vm_start_error(self, message: VMStartError) -> None:
        """Called when a VM fails to start."""
        self.show_error_message(f"Error starting {message.vm_name}: {message.error_message}")

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.value is not None:
            if str(event.value).startswith("sort_"):
                sort_key = str(event.value).replace("sort_", "")
                if self.sort_by != sort_key:
                    self.sort_by = sort_key
                    self.current_page = 0
                    self.refresh_vm_list()
        else:
            # Selection cleared
            if self.sort_by != "default":
                self.sort_by = "default"
                self.current_page = 0
                self.refresh_vm_list()

    @on(Button.Pressed, "#change_connection_button")
    def on_change_connection_button_pressed(self, event: Button.Pressed) -> None:
        self.push_screen(ConnectionModal(), self.handle_connection_result)

    @on(Button.Pressed, "#view_log_button")
    def action_view_log(self) -> None:
        """View the application log file."""
        log_file = "vm_manager_error.log"
        with self.app.suspend():
            subprocess.run(["view", log_file])

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
            self.change_connection(result)

    def change_connection(self, uri: str) -> None:
        """Change the connection URI and refresh the VM list."""
        if not uri or uri.strip() == "":
            return

        self.current_page = 0
        self.connect_libvirt(uri)
        self.refresh_vm_list()


    def refresh_vm_list(self) -> None:
        """Refreshes the list of VMs."""
        grid = self.query_one("#grid")
        grid.remove_children()
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
            conn_info = ""
            if self.connection_uri != "qemu:///system":
                conn_info = f" [{self.connection_uri}] | "

            self.sub_title = f"{conn_info}Total VMs: {total_vms}"
        except libvirt.libvirtError:
            self.show_error_message("Connection lost")
            self.conn = None


    def list_vms(self):
        grid = self.query_one("#grid")
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
                    grid.mount(vm_card)
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
        if self.current_page > 0:
            self.current_page -= 1
            self.refresh_vm_list()

    @on(Button.Pressed, "#next-button")
    def action_next_page(self) -> None:
        """Go to the next page."""
        if self.current_page < self.num_pages - 1:
            self.current_page += 1
            self.refresh_vm_list()

    def action_quit(self) -> None:
        """Quit the application."""
        self.exit()

if __name__ == "__main__":
    app = VMManagerTUI()
    app.run()
