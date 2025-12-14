"""
Main Interface
"""
import subprocess
import logging
import traceback
from datetime import datetime
import os
import libvirt

from textual.widgets import (
        Static, Button, TabbedContent,
        TabPane, Sparkline,
        )
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.message import Message
from textual import on
from textual.events import Click
from textual.css.query import NoMatches
from vm_queries import get_vm_disks_info, get_status
from vm_actions import clone_vm, rename_vm, start_vm

from modals.vmanager_xml_modals import XMLDisplayModal
from modals.utils_modals import ConfirmationDialog, LoadingModal
from vmcard_dialog import (
        DeleteVMConfirmationDialog,
        CloneNameDialog, RenameVMDialog, SelectSnapshotDialog, SnapshotNameDialog
        )
from utils import extract_server_name_from_uri
from config import load_config

# Load configuration once at module level
_config = load_config()

class VMNameClicked(Message):
    """Posted when a VM's name is clicked."""

    def __init__(self, vm_name: str, vm_uuid: str) -> None:
        super().__init__()
        self.vm_name = vm_name
        self.vm_uuid = vm_uuid

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

    def __init__(self, cpu_history: list[float] = None, mem_history: list[float] = None) -> None:
        super().__init__()
        self.cpu_history = cpu_history if cpu_history is not None else []
        self.mem_history = mem_history if mem_history is not None else []
        self.last_cpu_time = 0
        self.last_cpu_time_ts = 0

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
            uuid = self.vm.UUIDString()
            if self.app.webconsole_manager.is_running(uuid):
                if self.webc_status_indicator != " (WebC On)":
                    self.webc_status_indicator = " (WebC On)"
                return
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
            # Show VM name with server name
            if hasattr(self, 'conn') and self.conn:
                server_display = extract_server_name_from_uri(self.conn.getURI())
                yield Static(f"{self.name} ({server_display})", id="name", classes=classes)
            else:
                yield Static(self.name, id="name", classes=classes)
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
                            yield Button( "Configure", id="configure-button", variant="primary")
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
                        with Vertical():
                            yield Button("View XML", id="xml")
                            yield Static(classes="button-separator")
                            yield Button( "Rename", id="rename-button", variant="primary", classes="rename-button")

    def on_mount(self) -> None:
        self.styles.background = "#323232"
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
        self.timer.stop()

    def update_stats(self) -> None:
        """Update CPU and memory statistics."""
        self._update_webc_status() # Call on mount

        if self.vm:
            try:
                new_status = get_status(self.vm)
                if self.status != new_status:
                    self.status = new_status
                    status_widget = self.query_one("#status")
                    status_widget.update(f"Status: {self.status}{self.webc_status_indicator}")
                    self._update_status_styling()
                    self.update_button_layout()
            except libvirt.libvirtError as e:
                if e.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
                    self.app.refresh_vm_list()
                    return
                logging.warning(f"Libvirt error on refresh for {self.name}: {e}")
            except Exception as e:
                logging.error(f"Unexpected error refreshing status for {self.name}: {e}")

        if self.vm and self.vm.isActive():
            try:
                # CPU Usage
                stats = self.vm.getCPUStats(True)
                current_cpu_time = stats[0]['cpu_time']
                now = datetime.now().timestamp()

                if self.last_cpu_time > 0:
                    time_diff = now - self.last_cpu_time_ts
                    cpu_diff = current_cpu_time - self.last_cpu_time
                    if time_diff > 0:
                        # nanoseconds to seconds, then divide by number of cpus
                        cpu_percent = (cpu_diff / (time_diff * 1_000_000_000)) * 100
                        cpu_percent = cpu_percent / self.cpu # Divide by number of vCPUs
                        self.cpu_history = self.cpu_history[-20:] + [cpu_percent]
                        self.query_one("#cpu-sparkline").data = self.cpu_history

                self.last_cpu_time = current_cpu_time
                self.last_cpu_time_ts = now

                # Memory Usage
                mem_stats = self.vm.memoryStats()
                if 'rss' in mem_stats:
                    rss_kb = mem_stats['rss']
                    mem_percent = (rss_kb * 1024) / (self.memory * 1024 * 1024) * 100
                    self.mem_history = self.mem_history[-20:] + [mem_percent]
                    self.query_one("#mem-sparkline").data = self.mem_history

                if hasattr(self.app, "sparkline_data"):
                    uuid = self.vm.UUIDString()
                    self.app.sparkline_data[uuid]['cpu'] = self.cpu_history
                    self.app.sparkline_data[uuid]['mem'] = self.mem_history

            except libvirt.libvirtError as e:
                logging.error(f"Error getting stats for {self.name}: {e}")

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
            rename_button = self.query_one("#rename-button", Button)
            cpu_sparkline_container = self.query_one("#cpu-sparkline-container")
            mem_sparkline_container = self.query_one("#mem-sparkline-container")
            xml_button = self.query_one("#xml", Button)
        except NoMatches:
            pass

        is_stopped = self.status == "Stopped"
        is_running = self.status == "Running"
        is_paused = self.status == "Paused"
        has_snapshots = self.vm and self.vm.snapshotNum(0) > 0

        # Update Snapshot TabPane title
        tabbed_content = self.query_one(TabbedContent)
        snapshot_tab_pane = tabbed_content.get_pane("snapshot-tab")
        if snapshot_tab_pane:
            snapshot_tab_pane.title = self._get_snapshot_tab_title()

        start_button.display = is_stopped
        shutdown_button.display = is_running
        stop_button.display = is_running or is_paused
        delete_button.display = is_running or is_paused or is_stopped
        clone_button.display = is_stopped
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
        status_widget = self.query_one("#status")
        status_widget.remove_class("stopped", "running", "paused")
        status_widget.add_class(self.status.lower())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        button_handlers = {
            "start": self._handle_start_button,
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
            "rename-button": self._handle_rename_button,
            "configure-button": self._handle_configure_button,
        }
        handler = button_handlers.get(event.button.id)
        if handler:
            handler(event)

    def _handle_start_button(self, event: Button.Pressed) -> None:
        """Handles the start button press."""
        logging.info(f"Attempting to start VM: {self.name}")
        if not self.vm.isActive():
            try:
                start_vm(self.vm)
                #self.vm.create()
                self.app.refresh_vm_list()
                logging.info(f"Successfully started VM: {self.name}")
                self.app.show_success_message(f"VM '{self.name}' started successfully.")
            except Exception as e:
                self.app.show_error_message(f"Error on VM {self.name} during 'start': {e}")

    def _handle_shutdown_button(self, event: Button.Pressed) -> None:
        """Handles the shutdown button press."""
        logging.info(f"Attempting to gracefully shutdown VM: {self.name}")
        if self.vm.isActive():
            try:
                self.vm.shutdown()
                self.app.show_success_message(f"Shutdown signal sent to VM '{self.name}'.")
            except libvirt.libvirtError as e:
                self.app.show_error_message(f"Error on VM {self.name} during 'shutdown': {e}")

    def _handle_stop_button(self, event: Button.Pressed) -> None:
        """Handles the stop button press."""
        logging.info(f"Attempting to stop VM: {self.name}")

        def on_confirm(confirmed: bool) -> None:
            if not confirmed:
                return

            if self.vm.isActive():
                try:
                    self.vm.destroy()
                    self.app.refresh_vm_list()
                    logging.info(f"Successfully stopped VM: {self.name}")
                    self.app.show_success_message(f"VM '{self.name}' stopped successfully.")
                except libvirt.libvirtError as e:
                    self.app.show_error_message(f"Error on VM {self.name} during 'stop': {e}")

        message = f"This is a hard stop, like unplugging the power cord.\nAre you sure you want to stop '{self.name}'?"
        self.app.push_screen(ConfirmationDialog(message), on_confirm)

    def _handle_pause_button(self, event: Button.Pressed) -> None:
        """Handles the pause button press."""
        logging.info(f"Attempting to pause VM: {self.name}")
        if self.vm.isActive():
            try:
                self.vm.suspend()
                self.app.refresh_vm_list()
                logging.info(f"Successfully paused VM: {self.name}")
                self.app.show_success_message(f"VM '{self.name}' paused successfully.")
            except libvirt.libvirtError as e:
                self.app.show_error_message(f"Error on VM {self.name} during 'pause': {e}")

    def _handle_resume_button(self, event: Button.Pressed) -> None:
        """Handles the resume button press."""
        logging.info(f"Attempting to resume VM: {self.name}")
        try:
            self.vm.resume()
            self.app.refresh_vm_list()
            logging.info(f"Successfully resumed VM: {self.name}")
            self.app.show_success_message(f"VM '{self.name}' resumed successfully.")
        except libvirt.libvirtError as e:
            self.app.show_error_message(f"Error on VM {self.name} during 'resume': {e}")

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
        """Handles the connect button press."""
        logging.info(f"Attempting to connect to VM: {self.name}")
        if not hasattr(self, 'conn') or not self.conn:
            self.app.show_error_message("Connection info not available for this VM.")
            return
        try:
            uri = self.conn.getURI()
            subprocess.Popen(
                ["virt-viewer", "--connect", uri, self.name],
            )
            logging.info(f"Successfully launched virt-viewer for VM: {self.name}")
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            self.app.show_error_message(f"Error on VM {self.name} during 'connect': {e}")

    def _handle_web_console_button(self, event: Button.Pressed) -> None:
        """Handles the web console button press by delegating to the WebConsoleManager."""
        self.app.webconsole_manager.start_console(self.vm, self.conn)

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

        self.app.push_screen(SelectSnapshotDialog(snapshots, "Select snapshot to restore:"), restore_snapshot)

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

        self.app.push_screen(SelectSnapshotDialog(snapshots, "Select snapshot to delete:"), delete_snapshot)

    def _handle_delete_button(self, event: Button.Pressed) -> None:
        """Handles the delete button press."""
        logging.info(f"Attempting to delete VM: {self.name}")

        def on_confirm(result: tuple[bool, bool]) -> None:
            confirmed, delete_storage = result
            if not confirmed:
                return

            try:
                disk_paths = []
                if delete_storage:
                    xml_desc = self.vm.XMLDesc(0)
                    disks = get_vm_disks_info(self.vm.connect(), xml_desc)
                    disk_paths = [disk['path'] for disk in disks if disk.get('path')]

                if self.vm.isActive():
                    self.vm.destroy()
                self.vm.undefine()

                if delete_storage:
                    for path in disk_paths:
                        try:
                            if path and os.path.exists(path):
                                os.remove(path)
                                logging.info(f"Successfully deleted storage file: {path}")
                                self.app.show_success_message(f"Storage '{path}' deleted.")
                            else:
                                logging.warning(f"Storage file not found, skipping: {path}")
                        except OSError as e:
                            logging.error(f"Error deleting storage file {path}: {e}")
                            self.app.show_error_message(f"Error deleting storage '{path}': {e}")

                self.app.show_success_message(f"VM '{self.name}' deleted successfully.")
                self.app.refresh_vm_list()
                logging.info(f"Successfully deleted VM: {self.name}")
            except libvirt.libvirtError as e:
                self.app.show_error_message(f"Error on VM {self.name} during 'delete VM': {e}")
            except Exception as e:
                logging.error(f"An unexpected error occurred during VM deletion: {e}")
                self.app.show_error_message(f"An unexpected error occurred: {e}")

        self.app.push_screen(
            DeleteVMConfirmationDialog(self.name), on_confirm
        )

    def _handle_clone_button(self, event: Button.Pressed) -> None:
        """Handles the clone button press."""
        logging.info(f"Attempting to clone VM: {self.name}")

        def handle_clone_name(new_name: str | None) -> None:
            if new_name:
                loading_modal = LoadingModal()
                self.app.push_screen(loading_modal)

                def do_clone() -> None:
                    try:
                        clone_vm(self.vm, new_name)
                        self.app.call_from_thread(
                            self.app.show_success_message,
                            f"VM '{self.name}' cloned as '{new_name}' successfully."
                        )
                        self.app.call_from_thread(self.app.refresh_vm_list)
                        logging.info(f"Successfully cloned VM '{self.name}' to '{new_name}'")
                    except Exception as e:
                        self.app.call_from_thread(
                            self.app.show_error_message,
                            f"Error cloning VM {self.name}: {e}"
                        )
                    finally:
                        self.app.call_from_thread(loading_modal.dismiss)

                self.app.run_worker(do_clone, thread=True)

        self.app.push_screen(CloneNameDialog(), handle_clone_name)

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
        self.post_message(VMNameClicked(vm_name=self.name, vm_uuid=self.vm.UUIDString()))

    @on(Click, "#cpu-mem-info")
    def on_click_cpu_mem_info(self) -> None:
        """Handle clicks on the CPU/Memory info part of the VM card."""
        self.post_message(VMNameClicked(vm_name=self.name, vm_uuid=self.vm.UUIDString()))
