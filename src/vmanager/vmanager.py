"""
Main interface
"""
import os
import sys
import logging
import argparse
from typing import Any, Callable
import libvirt

from textual.app import App, ComposeResult, on
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import (
    Button, Footer, Header, Label, Link, Static,
)
from textual.worker import Worker, WorkerState

from config import load_config, save_config, get_log_path
from constants import (
        VmAction, VmStatus, ButtonLabels, ButtonIds,
        ErrorMessages, AppInfo
        )
from events import VmActionRequest, VMNameClicked, VMSelectionChanged
from libvirt_error_handler import register_error_handler
from libvirt_utils import _get_vm_names_from_uuids
from modals.bulk_modals import BulkActionModal
from modals.config_modal import ConfigModal
from modals.log_modal import LogModal
from modals.server_modals import ServerManagementModal
from modals.server_prefs_modals import ServerPrefModal
from modals.select_server_modals import SelectOneServerModal, SelectServerModal
from modals.vmanager_modals import (
    CreateVMModal,
    FilterModal,
)
from modals.vmdetails_modals import VMDetailModal
from modals.virsh_modals import VirshShellScreen
from utils import (
    check_novnc_path,
    check_virt_viewer,
    check_websockify,
    generate_webconsole_keys_if_needed,
)
from vm_queries import (
    check_for_spice_vms,
    get_status,
    get_vm_graphics_info,
    _get_domain_root,
    get_vm_cpu_details,
)
from vm_service import VMService
from vmcard import VMCard
from webconsole_manager import WebConsoleManager

# Configure logging
logging.basicConfig(
    filename=get_log_path(),
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


class WorkerManager:
    """A class to manage and track Textual workers."""

    def __init__(self, app: App):
        self.app = app
        self.workers: dict[str, Worker] = {}

    def run(
        self,
        callable: Callable[..., Any],
        *,
        name: str,
        group: str | None = None,
        exclusive: bool = True,
        thread: bool = True,
        description: str | None = None,
        exit_on_error: bool = True,
    ) -> Worker | None:
        """
        Runs and tracks a worker, preventing overlaps for workers with the same name.
        """
        if not exclusive and self.is_running(name):
            logging.warning(f"Worker '{name}' is already running. Skipping new run.")
            return None

        worker = self.app.run_worker(
            callable,
            name=name,
            thread=thread,
            group=group,
            exclusive=exclusive,
            description=description,
            exit_on_error=exit_on_error,
        )

        self.workers[name] = worker
        return worker

    def is_running(self, name: str) -> bool:
        """Check if a worker with the given name is currently running."""
        return name in self.workers and self.workers[name].state not in (
            WorkerState.SUCCESS,
            WorkerState.CANCELLED,
            WorkerState.ERROR,
        )

    def cancel(self, name: str) -> bool:
        """Cancel a running worker by name. Returns True if cancelled, False otherwise."""
        if name in self.workers:
            logging.info(f"Cancelling worker '{name}'.")
            self.workers[name].cancel()
            return True
        return False

    def cancel_all(self) -> None:
        """Cancel all running workers."""
        logging.info("Cancelling all running workers.")
        for worker in list(self.workers.values()):
            worker.cancel()
        self.workers.clear()

class VMManagerTUI(App):
    """A Textual application to manage VMs."""

    BINDINGS = [
        #("v", "view_log", "Log"),
        ("ctrl+v", "virsh_shell", "Virsh"),
        ("f", "filter_view", "Filter"),
        ("p", "server_preferences", "ServerPrefs"),
        ("c", "config", "Config"),
        ("m", "manage_server", "ServList"),
        ("s", "select_server", "SelServers"),
        ("ctrl+a", "toggle_select_all", "Sel/Des All"),
        ("q", "quit", "Quit"),
    ]

    config = load_config()
    servers = config.get('servers', [])
    virt_viewer_available = reactive(True)
    websockify_available = reactive(True)
    novnc_available = reactive(True)

    @staticmethod
    def _get_initial_active_uris(servers_list, autoconnect=False):
        if autoconnect and servers_list:
            return [servers_list[0]['uri']]
        return []

    active_uris = reactive(_get_initial_active_uris(servers, config.get('AUTOCONNECT_ON_STARTUP', False)))
    current_page = reactive(0)
    # changing that will break CSS value!
    VMS_PER_PAGE = config.get('VMS_PER_PAGE', 4)
    WC_PORT_RANGE_START = config.get('WC_PORT_RANGE_START')
    WC_PORT_RANGE_END = config.get('WC_PORT_RANGE_END')
    sort_by = reactive(VmStatus.DEFAULT)
    search_text = reactive("")
    num_pages = reactive(1)
    selected_vm_uuids: reactive[set[str]] = reactive(set)
    bulk_operation_in_progress = reactive(False)

    SERVER_COLOR_PALETTE = [
        "#33FF57",  # Green
        "#F333FF",  # Magenta
        "#3357FF",  # Blue
        "#FF8C33",  # Orange
        "#FF33A1",  # Pink
        "#F3FF33",  # Yellow
        "#33FF8C",  # Mint
        "#FF5733",  # Red-Orange
        "#33FFF3",  # Cyan
        "#A133FF",  # Purple
    ]

    CSS_PATH = ["vmanager.css", "vmcard.css", "dialog.css"]

    def __init__(self):
        super().__init__()
        self.vm_service = VMService()
        self.worker_manager = WorkerManager(self)
        self.webconsole_manager = WebConsoleManager(self)
        self.server_color_map = {}
        self._color_index = 0
        self.ui = {}
        self.devel = "(Devel v" + AppInfo.version + ")"
        self.vm_cards: dict[str, VMCard] = {}
        self._resize_timer = None

    def _cache_widgets(self) -> None:
        """Cache frequently accessed widgets."""
        try:
            self.ui = {
                "vms_container": self.query_one("#vms-container"),
                "error_footer": self.query_one("#error-footer"),
                "page_info": self.query_one("#page-info"),
                "pagination_controls": self.query_one("#pagination-controls"),
                "prev_button": self.query_one(f"#{ButtonIds.PREV_BUTTON}"),
                "next_button": self.query_one(f"#{ButtonIds.NEXT_BUTTON}"),
            }
        except Exception as e:
            logging.error(f"Failed to cache widgets: {e}")

    def get_server_color(self, uri: str) -> str:
        """Assigns and returns a consistent color for a given server URI."""
        if uri not in self.server_color_map:
            color = self.SERVER_COLOR_PALETTE[
                self._color_index % len(self.SERVER_COLOR_PALETTE)
            ]
            self.server_color_map[uri] = color
            self._color_index += 1
        return self.server_color_map[uri]

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        with Horizontal(classes="top-controls"):
            yield Button(
                ButtonLabels.SELECT_SERVER, id=ButtonIds.SELECT_SERVER_BUTTON, classes="Buttonpage"
            )
            yield Button(ButtonLabels.MANAGE_SERVERS, id=ButtonIds.MANAGE_SERVERS_BUTTON, classes="Buttonpage")
            yield Button(
                ButtonLabels.SERVER_PREFERENCES, id=ButtonIds.SERVER_PREFERENCES_BUTTON, classes="Buttonpage"
            )
            yield Button(ButtonLabels.FILTER_VM, id=ButtonIds.FILTER_BUTTON, classes="Buttonpage")
            yield Button(ButtonLabels.VIEW_LOG, id=ButtonIds.VIEW_LOG_BUTTON, classes="Buttonpage")
            # yield Button("Virsh Shell", id="virsh_shell_button", classes="Buttonpage")
            yield Button(ButtonLabels.BULK_CMD, id=ButtonIds.BULK_SELECTED_VMS, classes="Buttonpage")
            yield Button(ButtonLabels.CONFIG, id=ButtonIds.CONFIG_BUTTON, classes="Buttonpage")
            yield Link("About", url="https://aginies.github.io/virtui-manager/")

        with Horizontal(id="pagination-controls") as pc:
            pc.styles.display = "none"
            pc.styles.align_horizontal = "center"
            pc.styles.height = "auto"
            pc.styles.padding_bottom = 0
            yield Button(
                ButtonLabels.PREVIOUS_PAGE, id=ButtonIds.PREV_BUTTON, variant="primary", classes="ctrlpage"
            )
            yield Label("", id="page-info", classes="")
            yield Button(
                ButtonLabels.NEXT_PAGE, id=ButtonIds.NEXT_BUTTON, variant="primary", classes="ctrlpage"
            )

        with Vertical(id="vms-container"):
            pass

        yield Static(id="error-footer", classes="error-message")
        yield Footer()
        self.show_success_message(
            "In some Terminal use 'Shift' key while selecting text with the mouse to copy it."
        )

    def reload_servers(self, new_servers):
        self.servers = new_servers
        self.config["servers"] = new_servers
        save_config(self.config)

    def on_mount(self) -> None:
        """Called when the app is mounted."""
        register_error_handler()
        self.title = f"{AppInfo.namecase} {self.devel}"

        if not check_virt_viewer():
            self.show_error_message(
                ErrorMessages.VIRT_VIEWER_NOT_FOUND
            )
            self.virt_viewer_available = False

        if not check_websockify():
            self.show_error_message(
                ErrorMessages.WEBSOCKIFY_NOT_FOUND
            )
            self.websockify_available = False

        if not check_novnc_path():
            self.show_error_message(
                ErrorMessages.NOVNC_NOT_FOUND
            )
            self.novnc_available = False

        messages = generate_webconsole_keys_if_needed()
        for level, message in messages:
            if level == "info":
                self.show_success_message(message)
            else:
                self.show_error_message(message)

        self.sparkline_data = {}

        self._cache_widgets()

        error_footer = self.ui.get("error_footer")
        if error_footer:
            error_footer.styles.height = 0
            error_footer.styles.overflow = "hidden"
            error_footer.styles.padding = 0

        vms_container = self.ui.get("vms_container")
        if vms_container:
            vms_container.styles.grid_size_columns = 2
        # self._update_layout_for_size()

        if not self.servers:
            self.show_success_message(
                "No servers configured. Please add one via 'Servers List'."
            )

        for uri in self.active_uris:
            self.connect_libvirt(uri)
        # self.refresh_vm_list()

    def _update_layout_for_size(self):
        """Update the layout based on the terminal size."""
        vms_container = self.ui.get("vms_container")
        if not vms_container:
            # Fallback if UI not cached yet
            try:
                vms_container = self.query_one("#vms-container")
            except Exception:
                return

        width = self.size.width
        height = self.size.height
        cols = 2
        container_width = 86

        if width >= 212:
            cols = 5
            container_width = 213
        elif width >= 169:
            cols = 4
            container_width = 170
        elif width >= 128:
            cols = 3
            container_width = 129
        elif width >= 86:
            cols = 2
            container_width = 86
        else:  # width < 86
            cols = 2
            container_width = 84

        rows = 2  # Default to 2 rows
        if height > 42:
            rows = 3

        vms_container.styles.grid_size_columns = cols
        vms_container.styles.width = container_width
        self.VMS_PER_PAGE = cols * rows

        if width < 86:
            self.VMS_PER_PAGE = self.config.get("VMS_PER_PAGE", 4)

        self.refresh_vm_list()

    def on_resize(self, event):
        """Handle terminal resize events."""
        if self._resize_timer:
            self._resize_timer.stop()
        self._resize_timer = self.set_timer(0.5, self._update_layout_for_size)

    def on_unload(self) -> None:
        """Called when the app is about to be unloaded."""
        self.webconsole_manager.terminate_all()
        self.worker_manager.cancel_all()
        self.vm_service.disconnect_all()

    def _get_active_connections(self):
        """Generator that yields active libvirt connection objects."""
        for uri in self.active_uris:
            conn = self.vm_service.connect(uri)
            if conn:
                yield conn
            else:
                self.show_error_message(f"Failed to open connection to {uri}")

    def connect_libvirt(self, uri: str) -> None:
        """Connects to libvirt and runs slow checks in a worker."""
        conn = self.vm_service.connect(uri)
        if conn is None:
            self.show_error_message(f"Failed to connect to {uri}")
        else:
            if self.websockify_available and self.novnc_available:
                def check_spice():
                    """Worker to check for spice VMs without blocking."""
                    spice_message = check_for_spice_vms(conn)
                    if spice_message:
                        self.call_from_thread(self.show_success_message, spice_message)

                self.worker_manager.run(check_spice, name=f"check_spice_{uri}")

    def show_error_message(self, message: str):
        logging.error(message)
        self.notify(message, severity="error", timeout=10, title="Error!")

    def show_success_message(self, message: str):
        logging.info(message)
        self.notify(message, timeout=10, title="Info")

    @on(Button.Pressed, "#select_server_button")
    def action_select_server(self) -> None:
        """Select servers to connect to."""
        self.push_screen(SelectServerModal(self.servers, self.active_uris, self.vm_service), self.handle_select_server_result)

    def handle_select_server_result(self, selected_uris: list[str] | None) -> None:
        """Handle the result from the SelectServer screen."""
        if selected_uris is None: # User cancelled
            return

        logging.info(f"Servers selected: {selected_uris}")

        # Disconnect from servers that are no longer selected
        uris_to_disconnect = [uri for uri in self.active_uris if uri not in selected_uris]
        for uri in uris_to_disconnect:
            self.vm_service.disconnect(uri)

        self.active_uris = selected_uris
        self.current_page = 0

        self.refresh_vm_list()

    @on(Button.Pressed, "#filter_button")
    def action_filter_view(self) -> None:
        """Filter the VM list."""
        self.push_screen(FilterModal(current_search=self.search_text, current_status=self.sort_by))

    @on(FilterModal.FilterChanged)
    def on_filter_changed(self, message: FilterModal.FilterChanged) -> None:
        """Handle the FilterChanged message from the filter modal."""
        new_status = message.status
        new_search = message.search

        logging.info(f"Filter changed to status={new_status}, search='{new_search}'")

        status_changed = self.sort_by != new_status
        search_changed = self.search_text != new_search

        if status_changed or search_changed:
            self.sort_by = new_status
            self.search_text = new_search
            self.current_page = 0
            self.refresh_vm_list()

    def action_config(self) -> None:
        """Open the configuration modal."""
        self.push_screen(ConfigModal(self.config), self.handle_config_result)

    def handle_config_result(self, result: dict | None) -> None:
        """Handle the result from the ConfigModal."""
        if result:
            self.config = result
            # Potentially re-initiate connections or refresh UI if needed
            self.show_success_message("Configuration updated.")
            self.refresh_vm_list()

    @on(Button.Pressed, "#config_button")
    def on_config_button_pressed(self, event: Button.Pressed) -> None:
        """Callback for the config button."""
        self.action_config()

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
        if len(self.active_uris) > 1:
            self.show_error_message("VM creation is only supported when connected to a single server.")
            return
        self.push_screen(CreateVMModal(), self.handle_create_vm_result)

    @on(Button.Pressed, "#view_log_button")
    def action_view_log(self) -> None:
        """View the application log file."""
        log_path = get_log_path()
        try:
            with open(log_path, "r") as f:
                log_content = f.read()
        except FileNotFoundError:
            log_content = f"Log file ({log_path}) not found."
        except Exception as e:
            log_content = f"Error reading log file: {e}"
        self.push_screen(LogModal(log_content))

    @on(Button.Pressed, "#server_preferences_button")
    def action_server_preferences(self) -> None:
        """Show server preferences modal, prompting for a server if needed."""
        def launch_server_prefs(uri: str):
            self.push_screen(ServerPrefModal(uri=uri))

        self._select_server_and_run(launch_server_prefs, "Select a server for Preferences", "Open")

    def _select_server_and_run(self, callback: callable, modal_title: str, modal_button_label: str) -> None:
        """
        Helper to select a server and run a callback with the selected URI.
        Handles 0, 1, or multiple active servers.
        """
        if len(self.active_uris) == 0:
            self.show_error_message("Not connected to any server.")
            return

        if len(self.active_uris) == 1:
            callback(self.active_uris[0])
            return

        server_options = []
        for uri in self.active_uris:
            name = uri
            for server in self.servers:
                if server['uri'] == uri:
                    name = server['name']
                    break
            server_options.append({'name': name, 'uri': uri})

        def on_server_selected(uri: str | None):
            if uri:
                callback(uri)

        self.push_screen(SelectOneServerModal(server_options, title=modal_title, button_label=modal_button_label), on_server_selected)

    def action_virsh_shell(self) -> None:
        """Show the virsh shell modal."""
        def launch_virsh_shell(uri: str):
            self.push_screen(VirshShellScreen(uri=uri))

        self._select_server_and_run(launch_virsh_shell, "Select a server for Virsh Shell", "Launch")

    @on(Button.Pressed, "#virsh_shell_button")
    def on_virsh_shell_button_pressed(self, event: Button.Pressed) -> None:
        """Callback for the virsh shell button."""
        self.action_virsh_shell()

    @on(VMNameClicked)
    async def on_vm_name_clicked(self, message: VMNameClicked) -> None:
        """Callback when a VM's name is clicked. Fetches details via the VMService."""

        def get_details_and_show_modal():
            """Worker function to fetch VM details via the service."""
            try:
                result = self.vm_service.get_vm_details(self.active_uris, message.vm_uuid)

                if not result:
                    self.call_from_thread(
                        self.show_error_message,
                        f"VM {message.vm_name} with UUID {message.vm_uuid} not found on any active server."
                    )
                    return

                vm_info, domain, conn_for_domain = result

                def on_detail_modal_dismissed(result: None):
                    self.refresh_vm_list(force=True)

                self.call_from_thread(
                    self.push_screen,
                    VMDetailModal(message.vm_name, vm_info, domain, conn_for_domain, self.vm_service.invalidate_vm_cache),
                    on_detail_modal_dismissed
                )
            except libvirt.libvirtError as e:
                self.call_from_thread(
                    self.show_error_message,
                    f"Error getting details for {message.vm_name}: {e}",
                )

        self.worker_manager.run(
            get_details_and_show_modal, name=f"get_details_{message.vm_name}"
        )

    @on(VmActionRequest)
    def on_vm_action_request(self, message: VmActionRequest) -> None:
        """Handles a request to perform an action on a VM."""

        def action_worker():
            domain = self.vm_service.find_domain_by_uuid(self.active_uris, message.vm_uuid)
            if not domain:
                self.call_from_thread(self.show_error_message, f"Could not find VM with UUID {message.vm_uuid}")
                return

            vm_name = domain.name()
            try:
                if message.action == VmAction.START:
                    self.vm_service.start_vm(domain)
                    self.call_from_thread(self.show_success_message, f"VM '{vm_name}' started successfully.")
                elif message.action == VmAction.STOP:
                    self.vm_service.stop_vm(domain)
                    self.call_from_thread(self.show_success_message, f"Sent shutdown signal to VM '{vm_name}'.")
                elif message.action == VmAction.PAUSE:
                    self.vm_service.pause_vm(domain)
                    self.call_from_thread(self.show_success_message, f"VM '{vm_name}' paused successfully.")
                elif message.action == VmAction.FORCE_OFF:
                    self.vm_service.force_off_vm(domain)
                    self.call_from_thread(self.show_success_message, f"VM '{vm_name}' forcefully stopped.")
                elif message.action == VmAction.DELETE:
                    self.vm_service.delete_vm(domain, delete_storage=message.delete_storage)
                    self.vm_service.invalidate_domain_cache()
                    self.call_from_thread(self.show_success_message, f"VM '{vm_name}' deleted successfully.")
                elif message.action == VmAction.RESUME:
                    self.vm_service.resume_vm(domain)
                    self.call_from_thread(self.show_success_message, f"VM '{vm_name}' resumed successfully.")
                # Other actions (stop, pause, etc.) will be handled here in the future
                else:
                    self.call_from_thread(self.show_error_message, f"Unknown action '{message.action}' requested.")
                    return

                # If action was successful, refresh the list
                self.call_from_thread(self.refresh_vm_list)

            except Exception as e:
                self.call_from_thread(
                    self.show_error_message,
                    f"Error on VM '{vm_name}' during '{message.action}': {e}",
                )

        self.worker_manager.run(
            action_worker, name=f"action_{message.action}_{message.vm_uuid}"
        )

    def action_toggle_select_all(self) -> None:
        """Selects or deselects all VMs on the current page."""
        visible_cards = self.query(VMCard)
        if not visible_cards:
            return

        # If all visible cards are already selected, deselect them. Otherwise, select them.
        all_currently_selected = all(card.is_selected for card in visible_cards)

        target_selection_state = not all_currently_selected

        for card in visible_cards:
            card.is_selected = target_selection_state

    @on(VMSelectionChanged)
    def on_vm_selection_changed(self, message: VMSelectionChanged) -> None:
        """Handles when a VM's selection state changes."""
        if message.is_selected:
            self.selected_vm_uuids.add(message.vm_uuid)
        else:
            self.selected_vm_uuids.discard(message.vm_uuid)

    def handle_create_vm_result(self, result: dict | None) -> None:
        """Handle the result from the CreateVMModal and create the VM."""
        if not result:
            return

        conn = self.vm_service.connect(self.active_uris[0])
        if not conn:
            self.show_error_message("Not connected to libvirt. Cannot create VM.")
            return

        vm_name = result.get('name')
        memory = int(result.get('memory', 0))
        vcpu = int(result.get('vcpu', 0))
        disk_path = result.get('disk')

        if not all([vm_name, memory, vcpu, disk_path]):
            self.show_error_message("Missing VM details for creation.")
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
            conn.defineXML(xml)
            self.show_success_message(f"VM '{vm_name}' created successfully.")
            self.refresh_vm_list()
        except libvirt.libvirtError as e:
            self.show_error_message(f"Error creating VM '{vm_name}': {e}")

    def handle_bulk_action_result(self, result: dict | None) -> None:
        """Handles the result from the BulkActionModal."""
        if result is None:  # User cancelled or no action selected
            return

        action_type = result.get('action')
        delete_storage_flag = result.get('delete_storage', False)

        if not action_type:
            self.show_error_message("No action type received from bulk action modal.")
            return

        selected_uuids_copy = list(self.selected_vm_uuids)  # Take a copy for the worker

        # Clear selection immediately and set bulk operation flag
        self.selected_vm_uuids.clear()
        self.bulk_operation_in_progress = True

        # Perform the action in a worker to avoid blocking the UI
        self.worker_manager.run(
            lambda: self._perform_bulk_action_worker(
                action_type, selected_uuids_copy, delete_storage_flag
            ),
            name=f"bulk_action_{action_type}",
        )

    def _perform_bulk_action_worker(self, action_type: str, vm_uuids: list[str], delete_storage_flag: bool = False) -> None:
        """Worker function to orchestrate a bulk action using the VMService."""

        # Define a dummy progress callback
        def dummy_progress_callback(event_type: str, *args, **kwargs):
            pass

        try:
            successful_vms, failed_vms = self.vm_service.perform_bulk_action(
                self.active_uris,
                vm_uuids,
                action_type,
                delete_storage_flag,
                dummy_progress_callback  # Pass the dummy callback
            )

            summary = f"Bulk action '{action_type}' complete. Successful: {len(successful_vms)}, Failed: {len(failed_vms)}"
            logging.info(summary) 

            if successful_vms:
                self.call_from_thread(self.show_success_message, f"Bulk action '{action_type}' successful for {len(successful_vms)} VMs.")
            if failed_vms:
                self.call_from_thread(self.show_error_message, f"Bulk action '{action_type}' failed for {len(failed_vms)} VMs.")

        except Exception as e:
            logging.error(f"An unexpected error occurred during bulk action service call: {e}", exc_info=True)
            self.call_from_thread(self.show_error_message, f"A fatal error occurred during bulk action: {e}")

        finally:
            # Ensure these are called on the main thread
            force_refresh = action_type == VmAction.DELETE
            self.call_from_thread(self.refresh_vm_list, force=force_refresh)
            self.call_from_thread(setattr, self, 'bulk_operation_in_progress', False) # Reset flag


    def change_connection(self, uri: str) -> None:
        """Change the active connection to a single server and refresh."""
        logging.info(f"Changing connection to {uri}")
        if not uri or uri.strip() == "":
            return

        self.handle_select_server_result([uri])

    def refresh_vm_list(self, force: bool = False) -> None:
        """Refreshes the list of VMs by running the fetch-and-display logic in a worker."""
        # Try to run the worker. If it's already running, this will do nothing.
        self.worker_manager.run(lambda: self.list_vms_worker(force=force), name="list_vms")

    def list_vms_worker(self, force: bool = False):
        """Worker to fetch, filter, and display VMs using a diffing strategy."""
        try:
            domains_to_display, total_vms, total_filtered_vms, server_names = self.vm_service.get_vms(
                self.active_uris,
                self.servers,
                self.sort_by,
                self.search_text,
                self.selected_vm_uuids,
                force=force
            )
        except Exception as e:
            self.call_from_thread(self.show_error_message, f"Error fetching VM data: {e}")
            return

        if self.current_page > 0 and self.current_page * self.VMS_PER_PAGE >= total_filtered_vms:
            self.current_page = 0

        start_index = self.current_page * self.VMS_PER_PAGE
        end_index = start_index + self.VMS_PER_PAGE
        paginated_domains = domains_to_display[start_index:end_index]

        cards_to_mount = []
        page_uuids = set()

        for domain, conn in paginated_domains:
            try:
                uuid = domain.UUIDString()
                page_uuids.add(uuid)
                is_vm_selected = uuid in self.selected_vm_uuids
                
                vm_card = self.vm_cards.get(uuid)

                # Fetch info once
                info = domain.info()

                # Optimization: Only parse XML if strictly necessary (new card or forced refresh)
                cpu_details = None
                graphics_info = {}
                need_xml_parsing = not vm_card or force

                if need_xml_parsing:
                    _, root = _get_domain_root(domain)
                    cpu_details = get_vm_cpu_details(root)
                    graphics_info = get_vm_graphics_info(root)

                if vm_card:
                    # Update existing card
                    vm_card.name = domain.name() # Ensure name is updated
                    vm_card.status = get_status(domain, state=info[0])
                    vm_card.cpu = info[3]
                    vm_card.memory = info[1] // 1024
                    vm_card.is_selected = is_vm_selected
                    vm_card.vm = domain
                    vm_card.conn = conn
                    vm_card.server_border_color = self.get_server_color(conn.getURI())
                    
                    if need_xml_parsing:
                        vm_card.cpu_model = cpu_details or ""
                        vm_card.graphics_type = graphics_info.get("type", "vnc")
                else:
                    # Create new card
                    if uuid not in self.sparkline_data:
                        self.sparkline_data[uuid] = {"cpu": [], "mem": [], "disk": [], "net": []}

                    vm_card = VMCard(is_selected=is_vm_selected)
                    vm_card.name = domain.name()
                    vm_card.status = get_status(domain, state=info[0])
                    vm_card.cpu = info[3]
                    vm_card.memory = info[1] // 1024
                    vm_card.vm = domain
                    vm_card.conn = conn
                    vm_card.graphics_type = graphics_info.get("type", "vnc")
                    vm_card.server_border_color = self.get_server_color(conn.getURI())
                    vm_card.cpu_model = cpu_details or ""
                    self.vm_cards[uuid] = vm_card

                cards_to_mount.append(vm_card)
            except libvirt.libvirtError as e:
                if e.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
                    logging.warning(f"Skipping display of non-existent VM during refresh.")
                    continue
                else:
                    vm_name = "Unknown"
                    try:
                        vm_name = domain.name()
                    except libvirt.libvirtError:
                        pass
                    self.call_from_thread(self.show_error_message, f"Error getting info for VM '{vm_name}': {e}")
                    continue

        # Cleanup cache: remove cards for VMs that no longer exist at all
        all_uuids_from_libvirt = {dom.UUIDString() for dom, conn in domains_to_display}
        cached_uuids = set(self.vm_cards.keys())
        uuids_to_remove_from_cache = cached_uuids - all_uuids_from_libvirt

        for uuid in uuids_to_remove_from_cache:
            logging.info(f"Removing stale VM card from cache: {uuid}")
            # Card might be active on screen, so remove it before deleting from cache
            if self.vm_cards[uuid].is_mounted:
                self.vm_cards[uuid].remove()
            del self.vm_cards[uuid]
            if uuid in self.sparkline_data:
                del self.sparkline_data[uuid]

        def update_ui():
            vms_container = self.ui.get("vms_container")
            if not vms_container:
                return

            # Remove cards from container that are not in the new page layout
            for card in vms_container.query(VMCard):
                try:
                    # card.vm might be None if domain died
                    if not card.vm or card.vm.UUIDString() not in page_uuids:
                        card.remove()
                except (libvirt.libvirtError, AttributeError):
                    card.remove() # Stale/bad card

            # Mount the cards. This will add new ones and re-order existing ones.
            vms_container.mount(*cards_to_mount)

            self.sub_title = f"Servers: {', '.join(server_names)} | Total VMs: {total_vms}"
            self.update_pagination_controls(total_filtered_vms, total_vms_unfiltered=len(domains_to_display))

        self.call_from_thread(update_ui)


    def update_pagination_controls(self, total_filtered_vms: int, total_vms_unfiltered: int):
        pagination_controls = self.ui.get("pagination_controls")
        if not pagination_controls:
            return

        if total_vms_unfiltered <= self.VMS_PER_PAGE:
            pagination_controls.styles.display = "none"
            return
        else:
            pagination_controls.styles.display = "block"

        num_pages = (total_filtered_vms + self.VMS_PER_PAGE - 1) // self.VMS_PER_PAGE
        self.num_pages = num_pages

        page_info = self.ui.get("page_info")
        if page_info:
            page_info.update(f" [ {self.current_page + 1}/{num_pages} ]")

        prev_button = self.ui.get("prev_button")
        if prev_button:
            prev_button.disabled = self.current_page == 0

        next_button = self.ui.get("next_button")
        if next_button:
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

    @on(Button.Pressed, "#bulk_selected_vms")
    def on_bulk_selected_vms_button_pressed(self) -> None:
        """Handles the 'Bulk Selected' button press."""
        if not self.selected_vm_uuids:
            self.show_error_message("No VMs selected.")
            return

        def get_names_and_show_modal():
            """Worker to fetch VM names and display the bulk action modal."""
            all_names = set()
            uuids = list(self.selected_vm_uuids)
            connections = list(self._get_active_connections())

            for conn in connections:
                try:
                    names = _get_vm_names_from_uuids(conn, uuids)
                    if names:
                        all_names.update(names)
                except libvirt.libvirtError:
                    pass

            vm_names_list = sorted(list(all_names))

            if vm_names_list:
                self.call_from_thread(
                    self.push_screen, BulkActionModal(vm_names_list), self.handle_bulk_action_result
                )
            else:
                self.call_from_thread(
                    self.show_error_message, "Could not retrieve names for selected VMs."
                )

        self.worker_manager.run(
            get_names_and_show_modal,
            name="get_bulk_vm_names",
        )


    async def action_quit(self) -> None:
        """Quit the application."""
        self.exit()

def main():
    """Entry point for vmanager TUI application."""
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
        if terminal_size.columns < 86:
            print(f"Terminal width is too small ({terminal_size.columns} columns). Please resize to at least 86 columns.")
            sys.exit(1)
        app = VMManagerTUI()
        app.run()

if __name__ == "__main__":
    main()
