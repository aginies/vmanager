"""
VMcard Interface
"""
import subprocess
import logging
import traceback
from datetime import datetime
from functools import partial
from urllib.parse import urlparse
import xml.etree.ElementTree as ET
import libvirt

from textual.widgets import (
        Static, Button, TabbedContent,
        TabPane, Sparkline, Checkbox
        )
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.message import Message
from textual import on
from textual.events import Click
from textual.css.query import NoMatches

from events import VMNameClicked, VMSelectionChanged, VmActionRequest
from vm_queries import get_status
from vm_actions import clone_vm, delete_vm, rename_vm, start_vm

from modals.xml_modals import XMLDisplayModal
from modals.utils_modals import ConfirmationDialog, LoadingModal, ProgressModal
from modals.migration_modals import MigrationModal
from vmcard_dialog import (
        DeleteVMConfirmationDialog, WebConsoleConfigDialog,
        AdvancedCloneDialog, RenameVMDialog, SelectSnapshotDialog, SnapshotNameDialog
        )
from utils import extract_server_name_from_uri
from config import load_config, save_config

# Load configuration once at module level
_config = load_config()

class VMCard(Static):
    """
    Main VM card
    """
    name = reactive("")
    status = reactive("")
    cpu = reactive(0)
    memory = reactive(0)
    vm = reactive(None)
    conn = reactive(None)

    webc_status_indicator = reactive("")
    graphics_type = reactive("vnc")
    server_border_color = reactive("green")
    is_selected = reactive(False)

    def __init__(self, cpu_history: list[float] = None, mem_history: list[float] = None, is_selected: bool = False) -> None:
        super().__init__()
        self.cpu_history = cpu_history if cpu_history is not None else []
        self.mem_history = mem_history if mem_history is not None else []
        self.last_cpu_time = 0
        self.last_cpu_time_ts = 0
        self.is_selected = is_selected
        self.timer = None

    def _get_snapshot_tab_title(self) -> str:
        if self.vm:
            try:
                num_snapshots = self.vm.snapshotNum(0)
                if num_snapshots > 0 and num_snapshots < 2:
                    return f"Snapshot({num_snapshots})"
                elif num_snapshots > 1:
                    return f"Snapshots({num_snapshots})"
            except libvirt.libvirtError:
                pass # Domain might be transient or invalid
        return "Snapshot"

    def _update_webc_status(self) -> None:
        """Updates the web console status indicator."""
        if hasattr(self.app, 'webconsole_manager') and self.vm:
            try:
                uuid = self.vm.UUIDString()
                if self.app.webconsole_manager.is_running(uuid):
                    if self.webc_status_indicator != " (WebC On)":
                        self.webc_status_indicator = " (WebC On)"
                    return
            except libvirt.libvirtError as e:
                if e.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
                    pass # The VM is gone, let other parts handle the refresh.
                else:
                    logging.warning(f"Error getting UUID for webconsole status: {e}")

        if self.webc_status_indicator != "":
            self.webc_status_indicator = ""

    def watch_webc_status_indicator(self, old_value: str, new_value: str) -> None:
        """Called when webc_status_indicator changes."""
        try:
            status_widget = self.query_one("#status")
            status_text = f"Status: {self.status}{new_value}"
            status_widget.update(status_text)
        except NoMatches:
            # The widget hasn't been composed yet, ignore.
            pass

    def compose(self):
        with Vertical(id="info-container"):
            classes = ""
            with Horizontal(id="vm-header-row"):
                yield Checkbox("", id="vm-select-checkbox", classes="vm-select-checkbox", value=self.is_selected)
                with Vertical(): # New Vertical container for name and status
                    if hasattr(self, 'conn') and self.conn:
                        server_display = extract_server_name_from_uri(self.conn.getURI())
                        yield Static(f"{self.name} ({server_display})", id="vmname", classes="vmname")
                    else:
                        yield Static(self.name, id="vmname", classes="vmname")
                    status_class = self.status.lower()
                    yield Static(f"Status: {self.status}{self.webc_status_indicator}", id="status", classes=status_class)
            with Horizontal(id="cpu-sparkline-container", classes="sparkline-container"):
                cpu_spark = Static(f"{self.cpu} VCPU", id="cpu-mem-info", classes="sparkline-label")
                yield cpu_spark
                yield Sparkline(self.cpu_history, id="cpu-sparkline")
            with Horizontal(id="mem-sparkline-container", classes="sparkline-container"):
                mem_gb = round(self.memory / 1024, 1)
                mem_spark = Static(f"{mem_gb} Gb", id="cpu-mem-info", classes="sparkline-label")
                yield mem_spark
                yield Sparkline(self.mem_history, id="mem-sparkline")

            with TabbedContent(id="button-container"):
                with TabPane("Manage", id="manage-tab"):
                    with Horizontal():
                        with Vertical():
                            yield Button("Start", id="start", variant="success")
                            yield Button("Shutdown", id="shutdown", variant="primary")
                            yield Button("Force Off", id="stop", variant="error")
                            yield Button("Pause", id="pause", variant="primary")
                            yield Button("Resume", id="resume", variant="success")
                        with Vertical():
                            yield Button("Configure", id="configure-button", variant="primary")
                            yield Button("Web Console", id="web_console", variant="default")
                            yield Button("Connect", id="connect", variant="default")
                with TabPane(self._get_snapshot_tab_title(), id="snapshot-tab"):
                    with Horizontal():
                        with Vertical():
                            yield Button("Snapshot", id="snapshot_take", variant="primary")
                        with Vertical():
                            yield Button(
                                "Restore Snapshot",
                                id="snapshot_restore",
                                variant="primary",
                                )
                            yield Static(classes="button-separator")
                            yield Button(
                               "Del Snapshot",
                               id="snapshot_delete",
                               variant="error",
                               )
                with TabPane("Special", id="special-tab"):
                    with Horizontal():
                        with Vertical():
                            yield Button("Delete", id="delete", variant="success", classes="delete-button")
                            yield Static(classes="button-separator")
                            yield Button("Clone", id="clone", classes="clone-button")
                            yield Button("! Migration !", id="migration", variant="primary", classes="migration-button")
                        with Vertical():
                            yield Button("View XML", id="xml")
                            yield Static(classes="button-separator")
                            yield Button( "Rename", id="rename-button", variant="primary", classes="rename-button")

    def on_mount(self) -> None:
        self.styles.background = "#323232"
        if self.is_selected:
            self.styles.border = ("panel", "white")
        else:
            self.styles.border = ("solid", self.server_border_color)
        self.update_button_layout()
        self._update_status_styling()
        self._update_webc_status() # Call on mount
        self.update_stats()
        self.timer = self.set_interval(5, self.update_stats)

    def watch_server_border_color(self, old_color: str, new_color: str) -> None:
        """Called when server_border_color changes."""
        self.styles.border = ("solid", new_color)

    def on_unmount(self) -> None:
        """Stop the timer when the widget is removed."""
        if self.timer:
            self.timer.stop()

    def watch_is_selected(self, old_value: bool, new_value: bool) -> None:
        """Called when is_selected changes to update the checkbox."""
        try:
            checkbox = self.query_one("#vm-select-checkbox", Checkbox)
            checkbox.value = new_value
        except NoMatches:
            pass # Widget not yet composed, ignore

        if new_value:
            self.styles.border = ("panel", "white")
        else:
            self.styles.border = ("solid", self.server_border_color)

    def update_stats(self) -> None:
        """Schedules a worker to update CPU and memory statistics for the VM."""
        if not self.vm:
            return

        def update_worker():
            # This runs in a background thread
            try:
                stats = self.app.vm_service.get_vm_runtime_stats(self.vm)

                # This will be None if the domain is gone or inactive
                if not stats:
                    # If VM was previously running, update its state to reflect it's stopped.
                    if self.status != "Stopped":
                        def update_to_stopped():
                            self.status = "Stopped"
                            self._update_status_styling()
                            self.update_button_layout()
                            self.query_one("#cpu-sparkline-container").display = False
                            self.query_one("#mem-sparkline-container").display = False
                        self.app.call_from_thread(update_to_stopped)
                    return

                def apply_stats_to_ui():
                    # This runs on the main thread
                    # GUARD: If the widget has been unmounted in the meantime, do nothing.
                    if not self.is_mounted:
                        return

                    # Update status if changed
                    if self.status != stats['status']:
                        self.status = stats['status']
                        self._update_status_styling()
                        self.update_button_layout()
                    
                    # Update sparklines
                    self.cpu_history = self.cpu_history[-20:] + [stats['cpu_percent']]
                    self.mem_history = self.mem_history[-20:] + [stats['mem_percent']]
                    
                    try:
                        self.query_one("#cpu-sparkline").data = self.cpu_history
                        self.query_one("#mem-sparkline").data = self.mem_history
                    except NoMatches:
                        pass # Card may be unmounting, the guard should prevent most of this.

                    # Persist history for global refresh
                    if hasattr(self.app, "sparkline_data"):
                        uuid = self.vm.UUIDString()
                        if uuid in self.app.sparkline_data:
                            self.app.sparkline_data[uuid]['cpu'] = self.cpu_history
                            self.app.sparkline_data[uuid]['mem'] = self.mem_history
                
                self.app.call_from_thread(apply_stats_to_ui)

            except libvirt.libvirtError as e:
                # Handle cases where the VM disappears during the operation
                if e.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
                    if self.timer:
                        self.timer.stop()
                else:
                    logging.warning(f"Libvirt error during background stat update for {self.name}: {e}")
            except Exception as e:
                logging.error(f"Unexpected error in update_stats worker for {self.name}: {e}", exc_info=True)

        # Always check webc status on the main thread before starting the worker
        self._update_webc_status()
        self.app.run_worker(update_worker, thread=True, name=f"update_stats_{self.name}")

    def update_button_layout(self):
        """Update the button layout based on current VM status."""
        try:
            start_button = self.query_one("#start", Button)
            shutdown_button = self.query_one("#shutdown", Button)
            stop_button = self.query_one("#stop", Button)
            pause_button = self.query_one("#pause", Button)
            resume_button = self.query_one("#resume", Button)
            delete_button = self.query_one("#delete", Button)
            connect_button = self.query_one("#connect", Button)
            web_console_button = self.query_one("#web_console", Button)
            restore_button = self.query_one("#snapshot_restore", Button)
            snapshot_delete_button = self.query_one("#snapshot_delete", Button)
            info_button = self.query_one("#configure-button", Button)
            clone_button = self.query_one("#clone", Button)
            migration_button = self.query_one("#migration", Button)
            rename_button = self.query_one("#rename-button", Button)
            cpu_sparkline_container = self.query_one("#cpu-sparkline-container")
            mem_sparkline_container = self.query_one("#mem-sparkline-container")
            xml_button = self.query_one("#xml", Button)
        except NoMatches:
            # If any essential button isn't found, it means the card is likely being torn down.
            # Just return and avoid further updates.
            return

        is_stopped = self.status == "Stopped"
        is_running = self.status == "Running"
        is_paused = self.status == "Paused"
        has_snapshots = False
        try:
            if self.vm:
                has_snapshots = self.vm.snapshotNum(0) > 0
        except libvirt.libvirtError as e:
            if e.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
                self.app.refresh_vm_list()
                return
            logging.warning(f"Could not get snapshot count for {self.name}: {e}")

        # Update Snapshot TabPane title
        try:
            tabbed_content = self.query_one(TabbedContent)
            if not tabbed_content.is_mounted:
                return
            snapshot_tab_pane = tabbed_content.get_pane("snapshot-tab")
            # Only update the title if the widget is still mounted to prevent crashes
            if snapshot_tab_pane and self.is_mounted:
                snapshot_tab_pane.title = self._get_snapshot_tab_title()
        except NoMatches:
            pass

        start_button.display = is_stopped
        shutdown_button.display = is_running
        stop_button.display = is_running or is_paused
        delete_button.display = is_running or is_paused or is_stopped
        clone_button.display = is_stopped
        migration_button.display = True
        rename_button.display = is_stopped
        pause_button.display = is_running
        resume_button.display = is_paused
        connect_button.display = (is_running or is_paused) and self.app.virt_viewer_available
        web_console_button.display = (is_running or is_paused) and self.graphics_type == "vnc" and self.app.websockify_available and self.app.novnc_available
        restore_button.display = has_snapshots
        snapshot_delete_button.display = has_snapshots
        info_button.display = True # Always show info button

        cpu_sparkline_container.display = not is_stopped
        mem_sparkline_container.display = not is_stopped

        if is_stopped:
            xml_button.label = "Edit XML"
        else:
            xml_button.label = "View XML"


    def _update_status_styling(self):
        try:
            status_widget = self.query_one("#status")
            status_widget.remove_class("stopped", "running", "paused")
            status_widget.add_class(self.status.lower())
        except NoMatches:
            pass # Widget not found, likely torn down or not yet composed.

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        from constants import VmAction
        if event.button.id == "start":
            self.post_message(VmActionRequest(self.vm.UUIDString(), VmAction.START))
            return

        button_handlers = {
            "shutdown": self._handle_shutdown_button,
            "stop": self._handle_stop_button,
            "pause": self._handle_pause_button,
            "resume": self._handle_resume_button,
            "xml": self._handle_xml_button,
            "connect": self._handle_connect_button,
            "web_console": self._handle_web_console_button,
            "snapshot_take": self._handle_snapshot_take_button,
            "snapshot_restore": self._handle_snapshot_restore_button,
            "snapshot_delete": self._handle_snapshot_delete_button,
            "delete": self._handle_delete_button,
            "clone": self._handle_clone_button,
            "migration": self._handle_migration_button,
            "rename-button": self._handle_rename_button,
            "configure-button": self._handle_configure_button,
        }
        handler = button_handlers.get(event.button.id)
        if handler:
            handler(event)

    def _handle_shutdown_button(self, event: Button.Pressed) -> None:
        """Handles the shutdown button press."""
        from constants import VmAction
        logging.info(f"Attempting to gracefully shutdown VM: {self.name}")
        if self.vm.isActive():
            self.post_message(VmActionRequest(self.vm.UUIDString(), VmAction.STOP))


    def _handle_stop_button(self, event: Button.Pressed) -> None:
        """Handles the stop button press."""
        from constants import VmAction
        logging.info(f"Attempting to stop VM: {self.name}")

        def on_confirm(confirmed: bool) -> None:
            if not confirmed:
                return

            if self.vm.isActive():
                self.post_message(VmActionRequest(self.vm.UUIDString(), VmAction.FORCE_OFF))

        message = f"This is a hard stop, like unplugging the power cord.\nAre you sure you want to stop '{self.name}'?"
        self.app.push_screen(ConfirmationDialog(message), on_confirm)

    def _handle_pause_button(self, event: Button.Pressed) -> None:
        """Handles the pause button press."""
        from constants import VmAction
        logging.info(f"Attempting to pause VM: {self.name}")
        if self.vm.isActive():
            self.post_message(VmActionRequest(self.vm.UUIDString(), VmAction.PAUSE))

    def _handle_resume_button(self, event: Button.Pressed) -> None:
        """Handles the resume button press."""
        from constants import VmAction
        logging.info(f"Attempting to resume VM: {self.name}")
        self.post_message(VmActionRequest(self.vm.UUIDString(), VmAction.RESUME))

    def _handle_xml_button(self, event: Button.Pressed) -> None:
        """Handles the xml button press."""
        try:
            original_xml = self.vm.XMLDesc(0)
            is_stopped = self.status == "Stopped"

            def handle_xml_modal_result(modified_xml: str | None):
                if modified_xml and is_stopped:
                    if original_xml.strip() != modified_xml.strip():
                        try:
                            conn = self.vm.connect()
                            conn.defineXML(modified_xml)
                            self.app.show_success_message(f"VM '{self.name}' configuration updated successfully.")
                            logging.info(f"Successfully updated XML for VM: {self.name}")
                            self.app.refresh_vm_list()
                        except libvirt.libvirtError as e:
                            error_msg = f"Invalid XML for '{self.name}': {e}. Your changes have been discarded."
                            self.app.show_error_message(error_msg)
                            logging.error(error_msg)
                    else:
                        self.app.show_success_message("No changes made to the XML configuration.")

            self.app.push_screen(
                XMLDisplayModal(original_xml, read_only=not is_stopped),
                handle_xml_modal_result
            )
        except libvirt.libvirtError as e:
            self.app.show_error_message(f"Error getting XML for VM {self.name}: {e}")
        except Exception as e:
            self.app.show_error_message(f"An unexpected error occurred: {e}")
            logging.error(f"Unexpected error handling XML button: {traceback.format_exc()}")

    def _handle_connect_button(self, event: Button.Pressed) -> None:
        """Handles the connect button press by running virt-viewer in a worker."""
        logging.info(f"Attempting to connect to VM: {self.name}")
        if not hasattr(self, 'conn') or not self.conn:
            self.app.show_error_message("Connection info not available for this VM.")
            return

        def do_connect() -> None:
            try:
                uri = self.conn.getURI()
                domain_name = self.vm.name()

                command = ["virt-viewer", "--connect", uri, domain_name]
                logging.info(f"Executing command: {' '.join(command)}")

                result = subprocess.run(command, capture_output=True, text=True, check=False)

                if result.returncode != 0:
                    error_message = result.stderr.strip()
                    logging.error(f"virt-viewer failed for {domain_name}: {error_message}")
                    if "cannot open display" in error_message:
                        self.app.call_from_thread(
                            self.app.show_error_message, 
                            "Could not open display. Ensure you are in a graphical session."
                        )
                    else:
                        self.app.call_from_thread(
                            self.app.show_error_message,
                            f"virt-viewer failed: {error_message}"
                        )
                else:
                    logging.info(f"virt-viewer for {domain_name} closed.")

            except FileNotFoundError:
                self.app.call_from_thread(
                    self.app.show_error_message,
                    "virt-viewer command not found. Please ensure it is installed."
                )
            except libvirt.libvirtError as e:
                self.app.call_from_thread(
                    self.app.show_error_message,
                    f"Error getting VM details for {self.name}: {e}"
                )
            except Exception as e:
                logging.error(f"An unexpected error occurred during connect: {e}", exc_info=True)
                self.app.call_from_thread(
                    self.app.show_error_message,
                    "An unexpected error occurred while trying to connect."
                )

        self.app.run_worker(do_connect, thread=True)

    def _handle_web_console_button(self, event: Button.Pressed) -> None:
        """Handles the web console button press by opening a config dialog."""
        worker = partial(self.app.webconsole_manager.start_console, self.vm, self.conn)

        try:
            uuid = self.vm.UUIDString()
            if self.app.webconsole_manager.is_running(uuid):
                self.app.run_worker(worker, name=f"show_console_{self.vm.name()}", thread=True)
                return
        except libvirt.libvirtError as e:
            if e.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
                self.app.refresh_vm_list()
                return
            self.app.show_error_message(f"Error checking web console status for {self.name}: {e}")
            return

        parsed_uri = urlparse(self.conn.getURI())
        is_remote = parsed_uri.hostname not in (None, 'localhost', '127.0.0.1') and parsed_uri.scheme == 'qemu+ssh'

        if is_remote:
            def handle_dialog_result(should_start: bool) -> None:
                if should_start:
                    self.app.run_worker(worker,
                                        name=f"start_console_{self.vm.name()}",
                                        thread=True
                                        )

            self.app.push_screen(
                WebConsoleConfigDialog(is_remote=is_remote),
                handle_dialog_result
            )
        else:
            # Local connection, so webconsole must be local.
            # No need to show config dialog.
            config = load_config()
            if config.get('REMOTE_WEBCONSOLE') is not False:
                config['REMOTE_WEBCONSOLE'] = False
                save_config(config)
            self.app.run_worker(worker,
                                name=f"start_console_{self.vm.name()}",
                                thread=True
                                )

    def _handle_snapshot_take_button(self, event: Button.Pressed) -> None:
        """Handles the snapshot take button press."""
        logging.info(f"Attempting to take snapshot for VM: {self.name}")
        def handle_snapshot_name(name: str | None) -> None:
            if name:
                xml = f"<domainsnapshot><name>{name}</name></domainsnapshot>"
                try:
                    self.vm.snapshotCreateXML(xml, 0)
                    self.app.show_success_message(f"Snapshot '{name}' created successfully.")
                    self.app.refresh_vm_list()
                except libvirt.libvirtError as e:
                    self.app.show_error_message(f"Snapshot error for {self.name}: {e}")

        self.app.push_screen(SnapshotNameDialog(), handle_snapshot_name)

    def _handle_snapshot_restore_button(self, event: Button.Pressed) -> None:
        """Handles the snapshot restore button press."""
        logging.info(f"Attempting to restore snapshot for VM: {self.name}")
        snapshots = self.vm.listAllSnapshots(0)
        if not snapshots:
            self.app.show_error_message("No snapshots to restore.")
            return

        def restore_snapshot(snapshot_name: str | None) -> None:
            if snapshot_name:
                try:
                    snapshot = self.vm.snapshotLookupByName(snapshot_name, 0)
                    self.vm.revertToSnapshot(snapshot, 0)
                    self.app.refresh_vm_list()
                    self.app.show_success_message(f"Restored to snapshot '{snapshot_name}' successfully.")
                    logging.info(f"Successfully restored snapshot '{snapshot_name}' for VM: {self.name}")
                except libvirt.libvirtError as e:
                    self.app.show_error_message(f"Error on VM {self.name} during 'snapshot restore': {e}")

        self.app.push_screen(SelectSnapshotDialog(snapshots, "Select snapshot to restore"), restore_snapshot)

    def _handle_snapshot_delete_button(self, event: Button.Pressed) -> None:
        """Handles the snapshot delete button press."""
        logging.info(f"Attempting to delete snapshot for VM: {self.name}")
        snapshots = self.vm.listAllSnapshots(0)
        if not snapshots:
            self.app.show_error_message("No snapshots to delete.")
            return

        def delete_snapshot(snapshot_name: str | None) -> None:
            if snapshot_name:
                def on_confirm(confirmed: bool) -> None:
                    if confirmed:
                        try:
                            snapshot = self.vm.snapshotLookupByName(snapshot_name, 0)
                            snapshot.delete(0)
                            self.app.show_success_message(f"Snapshot '{snapshot_name}' deleted successfully.")
                            self.app.refresh_vm_list()
                            logging.info(f"Successfully deleted snapshot '{snapshot_name}' for VM: {self.name}")
                        except libvirt.libvirtError as e:
                            self.app.show_error_message(f"Error on VM {self.name} during 'snapshot delete': {e}")

                self.app.push_screen(
                    ConfirmationDialog(f"Are you sure you want to delete snapshot '{snapshot_name}'?"), on_confirm
                )

        self.app.push_screen(SelectSnapshotDialog(snapshots, "Select snapshot to delete"), delete_snapshot)

    def _handle_delete_button(self, event: Button.Pressed) -> None:
        """Handles the delete button press."""
        from constants import VmAction
        logging.info(f"Attempting to delete VM: {self.name}")

        def on_confirm(result: tuple[bool, bool]) -> None:
            confirmed, delete_storage = result
            if not confirmed:
                return

            self.post_message(VmActionRequest(self.vm.UUIDString(), VmAction.DELETE, delete_storage=delete_storage))

        self.app.push_screen(
            DeleteVMConfirmationDialog(self.name), on_confirm
        )

    def _handle_clone_button(self, event: Button.Pressed) -> None:
        """Handles the clone button press."""
        app = self.app

        def handle_clone_results(result: dict | None) -> None:
            if not result:
                return

            base_name = result["base_name"]
            count = result["count"]
            suffix = result["suffix"] # Retrieve the suffix

            progress_modal = ProgressModal(title=f"Cloning {self.name}...")
            app.push_screen(progress_modal)

            def log_callback(message: str):
                app.call_from_thread(progress_modal.add_log, message)

            def do_clone() -> None:
                log_callback(f"Attempting to clone VM: {self.name}")

                # Validate that new VM names do not already exist
                existing_vm_names = set()
                try:
                    all_domains = self.conn.listAllDomains(0)
                    for domain in all_domains:
                        existing_vm_names.add(domain.name())
                except libvirt.libvirtError as e:
                    log_callback(f"ERROR: Error getting existing VM names: {e}")
                    app.call_from_thread(app.show_error_message, f"Error getting existing VM names: {e}")
                    app.call_from_thread(progress_modal.dismiss)
                    return

                proposed_names = []
                for i in range(1, count + 1):
                    if count > 1:
                        new_name = f"{base_name}{suffix}{i}"
                    else:
                        new_name = base_name
                    proposed_names.append(new_name)
                log_callback(f"INFO: Proposed Name(s): {proposed_names}")

                conflicting_names = [name for name in proposed_names if name in existing_vm_names]

                if conflicting_names:
                    msg = f"The following VM names already exist: {', '.join(conflicting_names)}. Aborting cloning."
                    log_callback(f"ERROR: {msg}")
                    app.call_from_thread(app.show_error_message, msg)
                    app.call_from_thread(progress_modal.dismiss)
                    return
                else:
                    msg = "No Conflicting Name"
                    log_callback(f"INFO: {msg}")

                success_clones = []
                failed_clones = []

                # Set the total of the progress bar
                def set_progress_total():
                    pb = progress_modal.query_one("#progress-bar")
                    pb.total = count
                app.call_from_thread(set_progress_total)

                for i in range(1, count + 1):
                    if count > 1:
                        new_name = f"{base_name}{suffix}{i}"
                    else:
                        new_name = base_name

                    try:
                        log_callback(f"Cloning '{self.name}' to '{new_name}'...")
                        clone_vm(self.vm, new_name, log_callback=log_callback)
                        success_clones.append(new_name)
                        log_callback(f"Successfully cloned VM '{self.name}' to '{new_name}'")
                    except Exception as e:
                        failed_clones.append(new_name)
                        log_callback(f"ERROR: Error cloning VM {self.name} to {new_name}: {e}")
                    finally:
                        # Advance the progress bar
                        def advance_progress_bar():
                            pb = progress_modal.query_one("#progress-bar")
                            pb.advance(1)
                        app.call_from_thread(advance_progress_bar)

                # Show summary messages
                if success_clones:
                    msg = f"Successfully cloned to: {', '.join(success_clones)}"
                    app.call_from_thread(app.show_success_message, msg)
                    log_callback(msg)
                if failed_clones:
                    msg = f"Failed to clone to: {', '.join(failed_clones)}"
                    app.call_from_thread(app.show_error_message, msg)
                    log_callback(f"ERROR: {msg}")

                if success_clones:
                    app.call_from_thread(app.refresh_vm_list)

                app.call_from_thread(progress_modal.dismiss)

            app.run_worker(do_clone, thread=True)

        app.push_screen(AdvancedCloneDialog(), handle_clone_results)

    def _handle_rename_button(self, event: Button.Pressed) -> None:
        """Handles the rename button press."""
        logging.info(f"Attempting to rename VM: {self.name}")

        def handle_rename(new_name: str | None) -> None:
            if not new_name:
                return

            def do_rename(delete_snapshots=False):
                try:
                    rename_vm(self.vm, new_name, delete_snapshots=delete_snapshots)
                    msg = f"VM '{self.name}' renamed to '{new_name}' successfully."
                    if delete_snapshots:
                        msg = f"Snapshots deleted and VM '{self.name}' renamed to '{new_name}' successfully."
                    self.app.show_success_message(msg)
                    self.app.refresh_vm_list()
                    logging.info(f"Successfully renamed VM '{self.name}' to '{new_name}'")
                except Exception as e:
                    self.app.show_error_message(f"Error renaming VM {self.name}: {e}")

            num_snapshots = self.vm.snapshotNum(0)
            if num_snapshots > 0:
                def on_confirm_delete(confirmed: bool) -> None:
                    if confirmed:
                        do_rename(delete_snapshots=True)
                    else:
                        self.app.show_success_message("VM rename cancelled.")

                self.app.push_screen(
                    ConfirmationDialog(f"VM has {num_snapshots} snapshot(s). To rename, they must be deleted.\nDelete snapshots and continue?"),
                    on_confirm_delete
                )
            else:
                do_rename()

        self.app.push_screen(RenameVMDialog(current_name=self.name), handle_rename)

    def _handle_configure_button(self, event: Button.Pressed) -> None:
        """Handles the configure button press."""
        try:
            self.post_message(VMNameClicked(vm_name=self.name, vm_uuid=self.vm.UUIDString()))
        except libvirt.libvirtError as e:
            if e.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
                self.app.refresh_vm_list()
                return
            self.app.show_error_message(f"Error getting UUID for {self.name}: {e}")

    def _handle_migration_button(self, event: Button.Pressed) -> None:
        """Handles the migration button press."""
        # Get selected VM UUIDs from the central app state
        selected_vm_uuids = self.app.selected_vm_uuids

        selected_vms = []
        if selected_vm_uuids:
            # Convert UUIDs to libvirt.virDomain objects
            for uuid in selected_vm_uuids:
                found_domain = None
                for uri in self.app.active_uris:
                    conn = self.app.vm_service.connect(uri)
                    if conn:
                        try:
                            domain = conn.lookupByUUIDString(uuid)
                            selected_vms.append(domain)
                            found_domain = True
                            break
                        except libvirt.libvirtError:
                            continue
                if not found_domain:
                    self.app.show_error_message(f"Selected VM with UUID {uuid} not found on any active server.")
                    # Decide if we continue with other VMs or abort. For now, continue.
        
        # If no VMs are selected via checkboxes, default to the current VM (the one the button was clicked on).
        if not selected_vms:
            selected_vms = [self.vm]

        logging.info(f"Migration initiated for VMs: {[vm.name() for vm in selected_vms]}")

        source_conns = {vm.connect().getURI() for vm in selected_vms}
        if len(source_conns) > 1:
            self.app.show_error_message("Cannot migrate VMs from different source hosts at the same time.")
            return

        active_vms = [vm for vm in selected_vms if vm.isActive()]
        is_live = len(active_vms) > 0
        if is_live and len(active_vms) < len(selected_vms):
            self.app.show_error_message("Cannot migrate running/paused and stopped VMs at the same time. Please select VMs with the same state.")
            return

        # Get all active connections from the connection manager
        active_uris = self.app.vm_service.get_all_uris()
        all_connections = {}
        for uri in active_uris:
            conn = self.app.vm_service.get_connection(uri)
            if conn: # Ensure connection is valid
                all_connections[uri] = conn

        source_uri = selected_vms[0].connect().getURI()

        # Migration from localhost is not supported as it requires a full remote URI.
        if source_uri == "qemu:///system":
            self.app.show_error_message(
                "Migration from localhost (qemu:///system) is not supported.\n"
                "A full remote URI (e.g., qemu+ssh://user@host/system) is required."
            )
            return

        dest_uris = [uri for uri in active_uris if uri != source_uri]
        if not dest_uris:
            self.app.show_error_message("No destination servers available (all active servers are either the source, or there are no active servers).")
            return

        def on_confirm(confirmed: bool) -> None:
            if not confirmed:
                return
            self.app.push_screen(MigrationModal(vms=selected_vms, is_live=is_live, connections=all_connections))

        self.app.push_screen(ConfirmationDialog("Experimental Features! not yet fully tested!"), on_confirm)
        #self.app.push_screen(MigrationModal(vms=selected_vms, is_live=is_live, connections=all_connections))

    @on(Checkbox.Changed, "#vm-select-checkbox")
    def on_vm_select_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Handles when the VM selection checkbox is changed."""
        self.is_selected = event.value
        self.post_message(VMSelectionChanged(vm_uuid=self.vm.UUIDString(), is_selected=event.value))

    @on(Click, "#cpu-mem-info")
    def on_click_cpu_mem_info(self) -> None:
        """Handle clicks on the CPU/Memory info part of the VM card."""
        self.post_message(VMNameClicked(vm_name=self.name, vm_uuid=self.vm.UUIDString()))
