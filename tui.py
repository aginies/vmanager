from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Select, Button, Input, Label, Static
from textual.containers import ScrollableContainer, Grid, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual import on
import libvirt
from vmcard import VMCard, VMStateChanged, VMStartError, VMNameClicked
from vm_info import get_vm_info


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

    def __init__(self, vm_name: str, vm_info: dict) -> None:
        super().__init__()
        self.vm_name = vm_name
        self.vm_info = vm_info

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"Details for VM: {self.vm_name}")
            # Show basic info
            yield Label(f"Status: {self.vm_info.get('status', 'N/A')}")
            yield Label(f"CPU: {self.vm_info.get('cpu', 'N/A')}")
            yield Label(f"Memory: {self.vm_info.get('memory', 'N/A')} MB")
            yield Label(f"UUID: {self.vm_info.get('uuid', 'N/A')}")

            if "firmware" in self.vm_info:
                yield Label(f"Firmware: {self.vm_info['firmware']}")

            if "machine_type" in self.vm_info:
                yield Label(f"Machine Type: {self.vm_info['machine_type']}")

            if "disks" in self.vm_info:
                yield Label("Disks:")
                for disk in self.vm_info["disks"]:
                    yield Static(f"  {disk}", classes="disk-info")

            if "networks" in self.vm_info:
                yield Label("Networks:")
                for network in self.vm_info["networks"]:
                    yield Static(f"  {network}", classes="network-info")

            # Show XML button
            yield Button("View XML Config", variant="primary", id="view-xml-btn")
            yield Button("Close", variant="primary", id="close-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-btn":
            self.dismiss()
        elif event.button.id == "view-xml-btn":
            # Show the XML content in a new modal
            xml_content = self.vm_info.get("xml", "")
            self.app.push_screen(XMLModalScreen(xml_content))


class VMManagerTUI(App):
    """A Textual application to manage VMs."""

    BINDINGS = []

    show_description = reactive(False)
    connection_uri = reactive("qemu:///system")

    CSS = """
    #vms-container {
        height: auto;
    }
    ConnectionModal {
        align: center middle;
    }
    #connection-dialog {
        width: 60;
        height: auto;
        border: thick $background 80%;
        background: $surface;
        padding: 1 2;
    }
    #connection-dialog Label {
        width: 100%;
        content-align: center middle;
        margin-bottom: 1;
    }
    #connection-dialog Input {
        width: 100%;
        margin-bottom: 1;
    }
    #connection-dialog Horizontal {
        width: 100%;
        height: auto;
        align: center middle;
    }
    #connection-dialog Button {
        margin: 0 1;
    }
    Header {
        background: $primary;
        color: $text;
    }
    Footer {
        background: $primary;
        color: $text;
    }
    Select {
        width: 30;
        height: 2;
        margin: 0 0;
    }
    .disk-info {
        margin: 0 2;
        padding: 0 0;
        border-left: round;
    }
    """

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
        grid.styles.grid_gutter_vertical = 2
        grid.styles.grid_gutter_horizontal = 2
        self.update_header()
        self.list_vms()

    async def on_vm_state_changed(self, message: VMStateChanged) -> None:
        """Called when a VM's state changes."""
        self.update_header()
        self.set_timer(2, self.refresh_vm_list)

    async def on_vm_start_error(self, message: VMStartError) -> None:
        """Called when a VM fails to start."""
        self.sub_title = f"Error starting {message.vm_name}: {message.error_message}"
        self.set_timer(5, self.update_header)  # Revert header after 5 seconds

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
        conn = libvirt.open(self.connection_uri)
        if conn is None:
            return

        try:
            vm_info_list = get_vm_info(self.connection_uri)
            for vm_info in vm_info_list:
                if vm_info['name'] == message.vm_name:
                    print(f"Nom: {vm_info['name']}")
                    print(f"UUID: {vm_info['uuid']}")
                    print(f"État: {vm_info['status']}")
                    print(f"Description: {vm_info['description']}")
                    print(f"CPU: {vm_info['cpu']}")
                    print(f"Mémoire: {vm_info['memory']} MiB")
                    #print(f"Type de machine: {vm_info['machine_type']}")
                    print(f"Firmware: {vm_info['firmware']}")
                    print(f"Réseaux: {vm_info['networks']}")
                    print(f"Disques: {vm_info['disks']}")
                    break

            self.push_screen(VMDetailModal(message.vm_name, vm_info))

        except libvirt.libvirtError:
            pass
        finally:
            if conn is not None:
                conn.close()

    def handle_connection_result(self, result: str | None) -> None:
        """Handle the result from the connection modal."""
        if result:
            self.change_connection(result)

    def change_connection(self, uri: str) -> None:
        """Change the connection URI and refresh the VM list."""
        if not uri or uri.strip() == "":
            return

        # Test the connection first
        try:
            conn = libvirt.open(uri)
            if conn is None:
                self.sub_title = f"Failed to connect to {uri}"
                self.update_header()  # Update immediately to show error
                return
            conn.close()

            # Connection successful, update URI
            self.connection_uri = uri
            self.refresh_vm_list()

        except libvirt.libvirtError as e:
            self.sub_title = f"Connection error: {str(e)}"
            self.update_header()  # Update immediately to show error
            return

    def refresh_vm_list(self) -> None:
        """Refreshes the list of VMs."""
        grid = self.query_one("#grid")
        grid.remove_children()
        self.list_vms()
        self.update_header()

    def update_header(self):
        conn = libvirt.open(self.connection_uri)
        if conn is None:
            self.sub_title = f"Failed to open connection to {self.connection_uri}"
            return

        running_vms = 0
        stopped_vms = 0
        paused_vms = 0
        domains = conn.listAllDomains(0)
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

        self.sub_title = f"{conn_info}Total VMs: {total_vms} | Running: {running_vms} | Paused: {paused_vms} | Stopped: {stopped_vms}"
        conn.close()

    def get_status(self, domain):
        state = domain.info()[0]
        if state == libvirt.VIR_DOMAIN_RUNNING:
            return "Running"
        elif state == libvirt.VIR_DOMAIN_PAUSED:
            return "Paused"
        else:
            return "Stopped"

    def list_vms(self):
        grid = self.query_one("#grid")
        conn = None
        try:
            conn = libvirt.open(self.connection_uri)
            if conn is None:
                return

            domains = conn.listAllDomains(0)
            if domains is not None:
                for domain in domains:
                    info = domain.info()
                    vm_card = VMCard(
                        name=domain.name(),
                        status=self.get_status(domain),
                        description=self.get_vm_description(domain),
                        cpu=info[3],
                        memory=info[1] // 1024,  # Convert KiB to MiB
                        vm=domain,
                        color="#323232",
                        show_description=self.show_description,
                    )
                    grid.mount(vm_card)
        finally:
            if conn is not None:
                conn.close()

    def get_vm_description(self, domain):
        try:
            return domain.metadata(libvirt.VIR_DOMAIN_METADATA_DESCRIPTION, None)
        except libvirt.libvirtError:
            return "No description"


if __name__ == "__main__":
    app = VMManagerTUI()
    app.run()
