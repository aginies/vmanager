"""
Main Interface
"""
import subprocess
import logging
import tempfile
import traceback
from datetime import datetime
import os
from pathlib import Path
import libvirt
from urllib.parse import urlparse

from textual.widgets import (
        Static, Button, Input, ListView, ListItem, Label, TabbedContent,
        TabPane, Sparkline, Select, Checkbox, Link
        )
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.message import Message
from textual import on
from textual.events import Click
from textual.css.query import NoMatches
from vm_queries import get_vm_disks_info, get_vm_graphics_info, get_status
from vm_actions import clone_vm, rename_vm, start_vm

from modals.base_modals import BaseDialog
from modals.utils_modals import ConfirmationDialog, LoadingModal
from utils import find_free_port, check_is_firewalld_running

class VMNameClicked(Message):
    """Posted when a VM's name is clicked."""

    def __init__(self, vm_name: str) -> None:
        super().__init__()
        self.vm_name = vm_name

class DeleteVMConfirmationDialog(BaseDialog[tuple[bool, bool]]):
    """A dialog to confirm VM deletion with an option to delete storage."""

    def __init__(self, vm_name: str) -> None:
        super().__init__()
        self.vm_name = vm_name

    def compose(self):
        yield Vertical(
            Label(f"Are you sure you want to delete VM '{self.vm_name}'?", id="question"),
            Checkbox("Delete storage volumes", id="delete-storage-checkbox"),
            Horizontal(
                Button("Yes", variant="error", id="yes", classes="dialog-buttons"),
                Button("No", variant="primary", id="no", classes="dialog-buttons"),
                id="dialog-buttons",
            ),
            id="dialog",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "yes":
            delete_storage = self.query_one("#delete-storage-checkbox", Checkbox).value
            self.dismiss((True, delete_storage))
        else:
            self.dismiss((False, False))

    def action_cancel_modal(self) -> None:
        """Cancel the modal."""
        self.dismiss((False, False))


class ChangeNetworkDialog(BaseDialog[dict | None]):
    """A dialog to change a VM's network interface."""

    def __init__(self, interfaces: list[dict], networks: list[str]) -> None:
        super().__init__()
        self.interfaces = interfaces
        self.networks = networks

    def compose(self):
        interface_options = [(f"{iface['mac']} ({iface['network']})", iface['mac']) for iface in self.interfaces]
        network_options = [(str(net), str(net)) for net in self.networks]

        with Vertical(id="dialog", classes="info-container"):
            yield Label("Select interface and new network:")
            yield Select(interface_options, id="interface-select")
            yield Select(network_options, id="network-select")
            with Horizontal(id="dialog-buttons"):
                yield Button("Change", variant="success", id="change")
                yield Button("Cancel", variant="error", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "change":
            interface_select = self.query_one("#interface-select", Select)
            network_select = self.query_one("#network-select", Select)

            mac_address = interface_select.value
            new_network = network_select.value

            if mac_address is Select.BLANK or new_network is Select.BLANK:
                self.app.show_error_message("Please select an interface and a network.")
                return

            self.dismiss({"mac_address": mac_address, "new_network": new_network})
        else:
            self.dismiss(None)


class WebConsoleDialog(BaseDialog[str | None]):
    """A dialog to show the web console URL."""

    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url

    def compose(self):
        yield Vertical(
            Label("Web Console is running at"),
            Input(value=self.url, disabled=True),
            Link("Open Link To a Browser", url=self.url),
            Label(""),
            Horizontal(
                Button("Stop Web Console service", variant="error", id="stop"),
                Button("Close this Window", variant="primary", id="close"),
                id="dialog-buttons",
            ),
            id="dialog",
            classes="info-container",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "stop":
            self.dismiss("stop")
        else:
            self.dismiss(None)


class CloneNameDialog(BaseDialog[str | None]):
    """A dialog to ask for a new VM name when cloning."""

    def compose(self):
        yield Vertical(
            Label("Enter new VM name", id="question"),
            Input(placeholder="new_vm_name"),
            Horizontal(
                Button("Clone", variant="success", id="clone_vm"),
                Button("Cancel", variant="error", id="cancel"),
                id="dialog-buttons",
            ),
            id="dialog",
            classes="info-container",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "clone_vm":
            input_widget = self.query_one(Input)
            new_name = input_widget.value.strip()

            error = self.validate_name(new_name)
            if error:
                self.app.show_error_message(error)
                return

            self.dismiss(new_name)
        else:
            self.dismiss(None)


class RenameVMDialog(BaseDialog[str | None]):
    """A dialog to ask for a new VM name when renaming."""

    def __init__(self, current_name: str) -> None:
        super().__init__()
        self.current_name = current_name

    def compose(self):
        yield Vertical(
            Label(f"Current name: {self.current_name}"),
            Label("Enter new VM name", id="question"),
            Input(placeholder="new_vm_name"),
            Horizontal(
                Button("Rename", variant="success", id="rename_vm"),
                Button("Cancel", variant="error", id="cancel"),
                id="dialog-buttons",
            ),
            id="dialog",
            classes="info-container",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "rename_vm":
            input_widget = self.query_one(Input)
            new_name = input_widget.value.strip()

            error = self.validate_name(new_name)
            if error:
                self.app.show_error_message(error)
                return

            self.dismiss(new_name)
        else:
            self.dismiss(None)


class SelectSnapshotDialog(BaseDialog[str | None]):
    """A dialog to select a snapshot from a list."""

    def __init__(self, snapshots: list, prompt: str) -> None:
        super().__init__()
        self.snapshots = snapshots
        self.prompt = prompt

    def compose(self):
        yield Vertical(
            Label(self.prompt),
            ListView(
                *[ListItem(Label(snap.getName())) for snap in self.snapshots],
                id="snapshot-list",
            ),
            Button("Cancel", variant="error", id="cancel"),
            id="dialog",
        )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        snapshot_name = event.item.query_one(Label).renderable
        self.dismiss(str(snapshot_name))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)


class VMCard(Static):
    name = reactive("")
    status = reactive("")
    cpu = reactive(0)
    memory = reactive(0)
    vm = reactive(None)
    color = reactive("blue")
    webc_status_indicator = reactive("")
    graphics_type = reactive("vnc")

    def __init__(self, cpu_history: list[float] = None, mem_history: list[float] = None) -> None:
        super().__init__()
        self.cpu_history = cpu_history if cpu_history is not None else []
        self.mem_history = mem_history if mem_history is not None else []
        self.last_cpu_time = 0
        self.last_cpu_time_ts = 0

    def _update_webc_status(self) -> None:
        """Updates the web console status indicator."""
        if hasattr(self.app, 'websockify_processes') and self.vm:
            uuid = self.vm.UUIDString()
            if uuid in self.app.websockify_processes:
                proc, _, _, _ = self.app.websockify_processes[uuid]
                if proc.poll() is None: # Check if the process is still running
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
                with TabPane("Snapshot", id="snapshot-tab"):
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
        self.styles.background = self.color
        self.update_button_layout()
        self._update_status_styling()
        self._update_webc_status() # Call on mount
        self.update_stats()  # Initial update
        self.timer = self.set_interval(5, self.update_stats)

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


        is_stopped = self.status == "Stopped"
        is_running = self.status == "Running"
        is_paused = self.status == "Paused"
        has_snapshots = self.vm and self.vm.snapshotNum(0) > 0

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


    def _update_status_styling(self):
        status_widget = self.query_one("#status")
        status_widget.remove_class("stopped", "running", "paused")
        status_widget.add_class(self.status.lower())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start":
            logging.info(f"Attempting to start VM: {self.name}")
            if not self.vm.isActive():
                try:
                    start_vm(self.vm)
                    #self.vm.create()
                    self.status = "Running"
                    status_widget = self.query_one("#status")
                    status_widget.update(f"Status: {self.status}{self.webc_status_indicator}")
                    self._update_status_styling()
                    self.update_button_layout()
                    self.app.refresh_vm_list()
                    logging.info(f"Successfully started VM: {self.name}")
                    self.app.show_success_message(f"VM '{self.name}' started successfully.")
                except Exception as e:
                    self.app.show_error_message(f"Error on VM {self.name} during 'start': {e}")

        elif event.button.id == "shutdown":
            logging.info(f"Attempting to gracefully shutdown VM: {self.name}")
            if self.vm.isActive():
                try:
                    self.vm.shutdown()
                    self.app.show_success_message(f"Shutdown signal sent to VM '{self.name}'.")
                except libvirt.libvirtError as e:
                    self.app.show_error_message(f"Error on VM {self.name} during 'shutdown': {e}")

        elif event.button.id == "stop":
            logging.info(f"Attempting to stop VM: {self.name}")

            def on_confirm(confirmed: bool) -> None:
                if not confirmed:
                    return

                if self.vm.isActive():
                    try:
                        self.vm.destroy()
                        self.status = "Stopped"
                        self.query_one("#status").update(f"Status: {self.status}")
                        self._update_status_styling()
                        self.update_button_layout()
                        self.app.refresh_vm_list()
                        logging.info(f"Successfully stopped VM: {self.name}")
                        self.app.show_success_message(f"VM '{self.name}' stopped successfully.")
                    except libvirt.libvirtError as e:
                        self.app.show_error_message(f"Error on VM {self.name} during 'stop': {e}")

            message = f"This is a hard stop, like unplugging the power cord.\nAre you sure you want to stop '{self.name}'?"
            self.app.push_screen(ConfirmationDialog(message), on_confirm)

        elif event.button.id == "pause":
            logging.info(f"Attempting to pause VM: {self.name}")
            if self.vm.isActive():
                try:
                    self.vm.suspend()
                    self.status = "Paused"
                    status_widget = self.query_one("#status")
                    status_widget.update(f"Status: {self.status}{self.webc_status_indicator}")
                    self._update_status_styling()
                    self.update_button_layout()
                    self.app.refresh_vm_list()
                    logging.info(f"Successfully paused VM: {self.name}")
                    self.app.show_success_message(f"VM '{self.name}' paused successfully.")
                except libvirt.libvirtError as e:
                    self.app.show_error_message(f"Error on VM {self.name} during 'pause': {e}")
        elif event.button.id == "resume":
            logging.info(f"Attempting to resume VM: {self.name}")
            try:
                self.vm.resume()
                self.status = "Running"
                status_widget = self.query_one("#status")
                status_widget.update(f"Status: {self.status}{self.webc_status_indicator}")
                self._update_webc_status()
                self._update_status_styling()
                self.app.refresh_vm_list()
                logging.info(f"Successfully resumed VM: {self.name}")
                self.app.show_success_message(f"VM '{self.name}' resumed successfully.")
            except libvirt.libvirtError as e:
                self.app.show_error_message(f"Error on VM {self.name} during 'resume': {e}")
        elif event.button.id == "xml":
            logging.info(f"Attempting to view XML for VM: {self.name}")
            try:
                xml_content = self.vm.XMLDesc(0)
                with tempfile.NamedTemporaryFile(
                    mode="w+", delete=False, suffix=".xml"
                ) as tmpfile:
                    tmpfile.write(xml_content)
                    tmpfile.flush()
                    with self.app.suspend():
                        subprocess.run(["view", tmpfile.name], check=True)
                logging.info(f"Successfully viewed XML for VM: {self.name}")
            except (libvirt.libvirtError, FileNotFoundError, subprocess.CalledProcessError) as e:
                self.app.show_error_message(f"Error on VM {self.name} during 'view XML': {e}")
        elif event.button.id == "connect":
            logging.info(f"Attempting to connect to VM: {self.name}")
            try:
                subprocess.Popen(
                    ["virt-viewer", "--connect", self.app.connection_uri, self.name],
                )
                logging.info(f"Successfully launched virt-viewer for VM: {self.name}")
            except (FileNotFoundError, subprocess.CalledProcessError) as e:
                self.app.show_error_message(f"Error on VM {self.name} during 'connect': {e}")
        elif event.button.id == "web_console":
            logging.info(f"Web console requested for VM: {self.name}")

            def handle_web_console_dialog(result: str | None):
                if result == "stop":
                    uuid = self.vm.UUIDString()
                    if uuid in self.app.websockify_processes:
                        websockify_proc, _, _, ssh_info = self.app.websockify_processes[uuid]
                        websockify_proc.terminate() # Stop websockify

                        if ssh_info and ssh_info.get("control_socket"):
                            control_socket = ssh_info["control_socket"]
                            try:
                                stop_cmd = ["ssh", "-S", control_socket, "-O", "exit", "dummy-host"]
                                subprocess.run(stop_cmd, check=True, timeout=5, capture_output=True)
                                logging.info(f"SSH tunnel stopped for VM {self.name} using socket {control_socket}")
                            except FileNotFoundError:
                                self.app.show_error_message("'ssh' command not found.")
                            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                                logging.warning(f"Could not stop SSH tunnel cleanly for VM {self.name}: {e.stderr.decode() if e.stderr else e}")
                            finally:
                                if os.path.exists(control_socket):
                                    os.remove(control_socket)

                        del self.app.websockify_processes[uuid]
                        self.app.show_success_message("Web console stopped.")
                        self._update_webc_status() # Update status after stopping

            if not hasattr(self.app, 'websockify_processes'):
                self.app.websockify_processes = {}

            uuid = self.vm.UUIDString()
            if uuid in self.app.websockify_processes:
                proc, _, url, _ = self.app.websockify_processes[uuid]
                if proc.poll() is None:
                    self.app.push_screen(WebConsoleDialog(url), handle_web_console_dialog)
                    return
                else: # Process has terminated, remove it
                    del self.app.websockify_processes[uuid]
                    self._update_webc_status()

            try:
                xml_content = self.vm.XMLDesc(0)
                graphics_info = get_vm_graphics_info(xml_content)

                if graphics_info['type'] != 'vnc':
                    self.app.show_error_message("Web console only supports VNC graphics.")
                    return

                vnc_port = graphics_info.get('port')
                if not vnc_port or vnc_port == '-1':
                    self.app.show_error_message("Could not determine VNC port for the VM.")
                    return

                # --- SSH Tunnel Logic ---
                ssh_info = {}
                parsed_uri = urlparse(self.app.connection_uri)
                is_remote_ssh = parsed_uri.hostname not in (None, 'localhost', '127.0.0.1') and parsed_uri.scheme == 'qemu+ssh'

                vnc_target_host = graphics_info.get('address', '127.0.0.1')
                vnc_target_port = vnc_port

                if is_remote_ssh:
                    self.app.show_success_message(f"Remote connection detected. Setting up SSH tunnel...")
                    user = parsed_uri.username
                    host = parsed_uri.hostname
                    remote_user_host = f"{user}@{host}" if user else host

                    # Create a temporary socket for ssh control
                    # We use a temp directory to store the socket
                    temp_dir = tempfile.gettempdir()
                    socket_name = f"vmanager_ssh_{uuid}_{datetime.now().strftime('%Y%m%d%H%M%S')}.sock"
                    control_socket = os.path.join(temp_dir, socket_name)

                    tunnel_port = find_free_port(int(self.app.WC_PORT_RANGE_START),
                                                 int(self.app.WC_PORT_RANGE_END)
                                                 )

                    ssh_cmd = [
                        "ssh",
                        "-M", "-S", control_socket,
                        "-f", "-N",
                        "-L", f"{tunnel_port}:127.0.0.1:{vnc_port}",
                        remote_user_host
                    ]

                    try:
                        subprocess.run(ssh_cmd, check=True, timeout=10)
                        logging.info(f"SSH tunnel created for VM {self.name} via {control_socket}")
                        ssh_info = {"control_socket": control_socket}

                        # Websockify now connects to the local end of the tunnel
                        vnc_target_host = '127.0.0.1'
                        vnc_target_port = tunnel_port

                    except FileNotFoundError:
                        self.app.show_error_message("SSH command not found. Cannot create tunnel.")
                        return
                    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                        self.app.show_error_message(f"Failed to create SSH tunnel: {e}")
                        logging.error(f"SSH tunnel command failed: {' '.join(ssh_cmd)}")
                        return

                elif vnc_target_host in ['0.0.0.0', '::']:
                    vnc_target_host = '127.0.0.1'

                web_port = find_free_port(int(self.app.WC_PORT_RANGE_START), int(self.app.WC_PORT_RANGE_END))
                
                websockify_path = "/usr/bin/websockify"
                novnc_path = "/usr/share/novnc/"

                websockify_cmd = [
                    websockify_path, "--run-once", str(web_port),
                    f"{vnc_target_host}:{vnc_target_port}", "--web", novnc_path
                ]

                config_dir = Path.home() / '.config' / 'vmanager'
                cert_file = config_dir / 'cert.pem'
                key_file = config_dir / 'key.pem'
                url_scheme = "http"

                log_file_path = "vm_manager.log"
                with open(log_file_path, 'a') as log_file_handle:
                    if cert_file.exists() and key_file.exists():
                        websockify_cmd.extend(["--cert", str(cert_file), "--key", str(key_file)])
                        url_scheme = "https"
                        self.app.show_success_message("Found cert/key, using secure wss connection.")

                    proc = subprocess.Popen(websockify_cmd, stdout=subprocess.DEVNULL, stderr=log_file_handle)
                    
                    url = f"{url_scheme}://localhost:{web_port}/vnc.html?path=websockify"
                    self.app.websockify_processes[uuid] = (proc, web_port, url, ssh_info)
                    
                    self.app.push_screen(WebConsoleDialog(url), handle_web_console_dialog)
                    self._update_webc_status()

            except (libvirt.libvirtError, FileNotFoundError, Exception) as e:
                self.app.show_error_message(f"Failed to start web console: {e}")
                logging.error(f"Error during web console startup for VM {self.name}: {traceback.format_exc()}")


        elif event.button.id == "snapshot_take":
            logging.info(f"Attempting to take snapshot for VM: {self.name}")
            def handle_snapshot_name(name: str | None) -> None:
                if name:
                    xml = f"<domainsnapshot><name>{name}</name></domainsnapshot>"
                    try:
                        self.vm.snapshotCreateXML(xml, 0)
                        self.app.show_success_message(f"Snapshot '{name}' created successfully.")
                        self.update_button_layout()
                    except libvirt.libvirtError as e:
                        self.app.show_error_message(f"Snapshot error for {self.name}: {e}")

            self.app.push_screen(SnapshotNameDialog(), handle_snapshot_name)

        elif event.button.id == "snapshot_restore":
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

                        # Get new state and update card
                        state, _ = self.vm.state()
                        if state == libvirt.VIR_DOMAIN_RUNNING:
                            self.status = "Running"
                        elif state == libvirt.VIR_DOMAIN_PAUSED:
                            self.status = "Paused"
                        else:
                            self.status = "Stopped"

                        status_widget = self.query_one("#status")
                        status_widget.update(f"Status: {self.status}{self.webc_status_indicator}")
                        self._update_status_styling()
                        self.update_button_layout()

                        self.app.refresh_vm_list()
                        self.app.show_success_message(f"Restored to snapshot '{snapshot_name}' successfully.")
                        logging.info(f"Successfully restored snapshot '{snapshot_name}' for VM: {self.name}")
                    except libvirt.libvirtError as e:
                        self.app.show_error_message(f"Error on VM {self.name} during 'snapshot restore': {e}")

            self.app.push_screen(SelectSnapshotDialog(snapshots, "Select snapshot to restore:"), restore_snapshot)

        elif event.button.id == "snapshot_delete":
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
                                self.update_button_layout()
                                logging.info(f"Successfully deleted snapshot '{snapshot_name}' for VM: {self.name}")
                            except libvirt.libvirtError as e:
                                self.app.show_error_message(f"Error on VM {self.name} during 'snapshot delete': {e}")

                    self.app.push_screen(
                        ConfirmationDialog(f"Are you sure you want to delete snapshot '{snapshot_name}'?"), on_confirm
                    )

            self.app.push_screen(SelectSnapshotDialog(snapshots, "Select snapshot to delete:"), delete_snapshot)

        elif event.button.id == "delete":
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

        elif event.button.id == "clone":
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

        elif event.button.id == "rename-button":
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

        elif event.button.id == "configure-button":
            self.post_message(VMNameClicked(vm_name=self.name))

    @on(Click, "#cpu-mem-info")
    def on_click_cpu_mem_info(self) -> None:
        """Handle clicks on the CPU/Memory info part of the VM card."""
        self.post_message(VMNameClicked(vm_name=self.name))

class SnapshotNameDialog(BaseDialog[str | None]):
    """A dialog to ask for a snapshot name."""

    def compose(self):
        yield Vertical(
            Label("Enter snapshot name", id="question"),
            Input(placeholder="snapshot_name"),
            Horizontal(
                Button("Create", variant="success", id="create"),
                Button("Cancel", variant="error", id="cancel"),
                id="dialog-buttons",
            ),
            id="dialog",
            classes="info-container",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create":
            input_widget = self.query_one(Input)
            snapshot_name = input_widget.value.strip()

            error = self.validate_name(snapshot_name)
            if error:
                self.app.show_error_message(error)
                return

            self.dismiss(snapshot_name)
        else:
            self.dismiss(None)


