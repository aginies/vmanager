"""
Main interface
"""
import os
import sys
import logging
import argparse

from textual.app import App, ComposeResult
from textual.widgets import (
        Header, Footer, Button, Label, Static,
        Link,
        )
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual import on
import libvirt

from libvirt_error_handler import register_error_handler
from vmcard import VMCard, VMNameClicked
from vm_queries import (
    get_status, get_vm_description, get_vm_machine_info, get_vm_firmware_info,
    get_vm_networks_info, get_vm_network_ip, get_vm_network_dns_gateway_info,
    get_vm_disks_info, get_vm_devices_info, get_vm_shared_memory_info,
    get_boot_info, get_vm_video_model,
    get_vm_cpu_model, get_vm_graphics_info,
    check_for_spice_vms,
)
from config import load_config, save_config
from utils import (
        generate_webconsole_keys_if_needed, check_virt_viewer,
        check_websockify, check_novnc_path
)
from modals.log_modal import LogModal
from modals.server_modals import ServerManagementModal
from modals.vmanager_modals import (
        FilterModal, CreateVMModal,
        )
from modals.server_prefs_modals import ServerPrefModal
from modals.vmanager_vmdetails_modals import VMDetailModal
from modals.vmanager_virsh_modals import VirshShellScreen

# Configure logging
logging.basicConfig(
    filename='vm_manager.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class VMManagerTUI(App):
    """A Textual application to manage VMs."""

    BINDINGS = [
        ("v", "view_log", "Log"),
        ("ctrl+v", "virsh_shell", "Virsh Shell"),
        ("f", "filter_view", "Filter"),
        ("p", "server_preferences", "Server Pref"),
        ("m", "manage_server", "Servers List"),
        ("q", "quit", "Quit"),
    ]

    config = load_config()
    servers = config.get('servers', [])
    virt_viewer_available = reactive(True)
    websockify_available = reactive(True)
    novnc_available = reactive(True)

    @staticmethod
    def _get_initial_connection_uri(servers_list):
        if servers_list:
            return servers_list[0]['uri']
        return "qemu:///system"

    connection_uri = reactive(_get_initial_connection_uri(servers))
    conn = None
    current_page = reactive(0)
    websockify_processes = {}
    # changing that will break CSS value!
    VMS_PER_PAGE = config.get('VMS_PER_PAGE', 4)
    WC_PORT_RANGE_START = config.get('WC_PORT_RANGE_START')
    WC_PORT_RANGE_END = config.get('WC_PORT_RANGE_END')
    sort_by = reactive("default")
    search_text = reactive("")
    num_pages = reactive(1)

    CSS_PATH = ["vmanager.css", "vmcard.css", "dialog.css"]

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        with Horizontal(classes="top-controls"):
            yield Button("Server Pref", id="server_preferences_button", classes="Buttonpage")
            yield Button("Servers List", id="manage_servers_button", classes="Buttonpage")
            #yield Button("Create VM", id="create_vm_button", classes="Buttonpage")
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
        self.show_success_message("In some Terminal use 'Shift' key while selecting text with the mouse to copy it.")

    def reload_servers(self, new_servers):
        self.servers = new_servers
        self.config['servers'] = new_servers
        save_config(self.config)

    def on_mount(self) -> None:
        """Called when the app is mounted."""
        register_error_handler()
        self.title = "Rainbow V Manager"

        if not check_virt_viewer():
            self.show_error_message("'virt-viewer' is not installed. 'Connect' button will be disabled.")
            self.virt_viewer_available = False

        if not check_websockify():
            self.show_error_message("'websockify' is not installed. 'Web Console' button will be disabled.")
            self.websockify_available = False

        if not check_novnc_path():
            self.show_error_message("'novnc' is not installed. 'Web Console' button will be disabled.")
            self.novnc_available = False

        messages = generate_webconsole_keys_if_needed()
        for level, message in messages:
            if level == 'info':
                self.show_success_message(message)
            else:
                self.show_error_message(message)

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
        for proc, _ in self.websockify_processes.values():
            proc.terminate()
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
                if self.websockify_available and self.novnc_available:
                    spice_message = check_for_spice_vms(self.conn)
                    if spice_message:
                        self.show_success_message(spice_message)
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

    def handle_server_selection_result(self, uri: str | None) -> None:
        """Handle the result from the server selection modal."""
        if uri:
            logging.info(f"Server selected: {uri}")
            self.change_connection(uri)

    def on_server_management(self, result: list | str | None) -> None:
        """Callback for ServerManagementModal."""
        if result is None:
            return
        if isinstance(result, list):
            self.reload_servers(result)
            return

        server_uri = result
        if server_uri:
            self.change_connection(server_uri)

    @on(Button.Pressed, "#manage_servers_button")
    def action_manage_server(self) -> None:
        """Manage the list of servers."""
        self.push_screen(ServerManagementModal(self.servers), self.on_server_management)

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
                xml_content = domain.XMLDesc(0)
                graphics_info = get_vm_graphics_info(xml_content)
                vm_card.graphics_type = graphics_info.get("type", "vnc")
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
    parser = argparse.ArgumentParser(description="A Textual application to manage VMs.")
    parser.add_argument("--cmd", action="store_true", help="Run in command-line interpreter mode.")
    args = parser.parse_args()

    if args.cmd:
        from vmanager_cmd import VManagerCMD
        VManagerCMD().cmdloop()
    else:
        terminal_size = os.get_terminal_size()
        if terminal_size.lines < 34:
            print(f"Terminal height is too small ({terminal_size.lines} lines). Please resize to at least 34 lines.")
            sys.exit(1)
        if terminal_size.columns < 92:
            print(f"Terminal width is too small ({terminal_size.columns} columns). Please resize to at least 92 columns.")
            sys.exit(1)

        app = VMManagerTUI()
        app.run()
