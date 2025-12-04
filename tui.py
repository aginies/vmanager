from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Select, Button, Input, Label
from textual.containers import ScrollableContainer, Grid, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
import libvirt
from vmcard import VMCard, VMStateChanged, VMStartError

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


class VMManagerTUI(App):
    """A Textual application to manage VMs."""

    BINDINGS = []

    show_description = reactive(False)
    show_machine_type = reactive(False)
    show_firmware = reactive(False)
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
    """

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        yield Select(
            [
                ("Show All", "show_all"),
                ("Hide All", "hide_all"),
                ("Toggle Description", "toggle_description"),
                ("Toggle Machine Type", "toggle_machine_type"),
                ("Toggle Firmware", "toggle_firmware"),
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
        self.set_timer(1, self.update_header)
        self.set_timer(2, self.refresh_vm_list)

    async def on_vm_start_error(self, message: VMStartError) -> None:
        """Called when a VM fails to start."""
        self.sub_title = f"Error starting {message.vm_name}: {message.error_message}"
        self.set_timer(5, self.update_header)  # Revert header after 5 seconds

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.value == "toggle_description":
            self.show_description = not self.show_description
        elif event.value == "toggle_machine_type":
            self.show_machine_type = not self.show_machine_type
        elif event.value == "toggle_firmware":
            self.show_firmware = not self.show_firmware
        elif event.value == "show_all":
            self.show_description = True
            self.show_machine_type = True
            self.show_firmware = True
        elif event.value == "hide_all":
            self.show_description = False
            self.show_machine_type = False
            self.show_firmware = False
        elif event.value == "change_connection":
            self.push_screen(ConnectionModal(), self.handle_connection_result)
            return

        self.refresh_vm_list()

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
                self.set_timer(5, self.update_header)
                return
            conn.close()

            # Connection successful, update URI
            self.connection_uri = uri
            self.refresh_vm_list()

        except libvirt.libvirtError as e:
            self.sub_title = f"Connection error: {str(e)}"
            self.set_timer(5, self.update_header)
            return
            conn.close()

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
                        show_machine_type=self.show_machine_type,
                        show_firmware=self.show_firmware,
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
