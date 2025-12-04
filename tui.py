from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Select, Button, Input, Label, Static
from textual.containers import ScrollableContainer, Grid, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual import on
import libvirt
from vmcard import VMCard, VMStateChanged, VMStartError, VMNameClicked
from vm_info import get_vm_info, get_status, get_vm_description, get_vm_machine_info, get_vm_firmware_info, get_vm_networks_info, get_vm_network_ip, get_vm_network_dns_gateway_info, get_vm_disks_info, get_vm_devices_info


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
                yield Button("Connect", variant="primary", id="connect-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "connect-btn":
            uri_input = self.query_one("#uri-input", Input)
            self.dismiss(uri_input.value)
        elif event.button.id == "cancel-btn":
            self.dismiss(None)


class XMLModalScreen(ModalScreen):
    """Modal screen to show VM XML configuration."""

    def __init__(self, xml_content: str) -> None:
        super().__init__()
        self.xml_content = xml_content

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("VM XML Configuration:")
            yield Static(self.xml_content, id="xml-content")
            yield Button("Close", variant="primary", id="close-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-btn":
            self.dismiss()


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
                yield Button("View XML", variant="primary", id="view-xml-btn")
                yield Button("Close", variant="default", id="close-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-btn":
            self.dismiss()
        elif event.button.id == "view-xml-btn":
            xml_content = self.vm_info.get("xml", "")
            if xml_content:
                self.app.push_screen(XMLModalScreen(xml_content))


class VMManagerTUI(App):
    """A Textual application to manage VMs."""

    BINDINGS = []

    show_description = reactive(False)
    connection_uri = reactive("qemu:///system")
    conn = None

    CSS_PATH = ["tui.css", "vmcard.css"]
    sub_title = reactive("")

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        yield Select(
            [
                ("Show All", "show_all"),
                ("Hide All", "hide_all"),
                ("Toggle Description", "toggle_description"),
                ("Change Connection", "change_connection"),
            ],
            id="select",
            prompt="Display options",
            allow_blank=True,
        )
        with ScrollableContainer(id="vms-container"):
            yield Grid(id="grid")

        yield Footer()

    def on_mount(self) -> None:
        """Called when the app is mounted."""
        self.title = "VM Manager"
        grid = self.query_one("#grid")
        grid.styles.grid_size_columns = 3
        grid.styles.grid_gutter_vertical = 1
        grid.styles.grid_gutter_horizontal = 1
        self.connect_libvirt(self.connection_uri)
        self.update_header()
        self.list_vms()

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
                self.sub_title = f"Failed to connect to {uri}"
            else:
                self.connection_uri = uri
        except libvirt.libvirtError as e:
            self.sub_title = f"Connection error: {e}"
            self.conn = None

    async def on_vm_state_changed(self, message: VMStateChanged) -> None:
        """Called when a VM's state changes."""
        self.set_timer(5, self.refresh_vm_list)
        self.set_timer(2, self.update_header)  # Revert header after 5 seconds

    async def on_vm_start_error(self, message: VMStartError) -> None:
        """Called when a VM fails to start."""
        self.sub_title = f"Error starting {message.vm_name}: {message.error_message}"
        self.set_timer(2, self.update_header)  # Revert header after 5 seconds

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.value == "toggle_description":
            self.show_description = not self.show_description
        elif event.value == "show_all":
            self.show_description = True
        elif event.value == "hide_all":
            self.show_description = False
        elif event.value == "change_connection":
            self.push_screen(ConnectionModal(), self.handle_connection_result)
            return

        self.refresh_vm_list()

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
        except libvirt.libvirtError:
            pass


    def handle_connection_result(self, result: str | None) -> None:
        """Handle the result from the connection modal."""
        if result:
            self.change_connection(result)

    def change_connection(self, uri: str) -> None:
        """Change the connection URI and refresh the VM list."""
        if not uri or uri.strip() == "":
            return

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
            self.sub_title = f"Failed to open connection to {self.connection_uri}"
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
            self.sub_title = "Connection lost"
            self.conn = None


    def list_vms(self):
        grid = self.query_one("#grid")
        if not self.conn:
            return

        try:
            domains = self.conn.listAllDomains(0)
            if domains is not None:
                for domain in domains:
                    info = domain.info()
                    vm_card = VMCard(
                        name=domain.name(),
                        status=get_status(domain),
                        description=get_vm_description(domain),
                        cpu=info[3],
                        memory=info[1] // 1024,  # Convert KiB to MiB
                        vm=domain,
                        color="#323232",
                        show_description=self.show_description,
                    )
                    grid.mount(vm_card)
        except libvirt.libvirtError:
            self.sub_title = "Connection lost"
            self.conn = None


if __name__ == "__main__":
    app = VMManagerTUI()
    app.run()
