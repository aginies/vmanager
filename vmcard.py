import subprocess
import tempfile
import libvirt
import logging
from datetime import datetime
import vm_info
import re

from textual.widgets import Static, Button, Input, ListView, ListItem, Label, TabbedContent, TabPane, Sparkline, Select
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.message import Message
from textual.screen import Screen
from textual import on
from textual.events import Click
from typing import TypeVar
from textual.timer import Timer

T = TypeVar("T")

class VMNameClicked(Message):
    """Posted when a VM's name is clicked."""

    def __init__(self, vm_name: str) -> None:
        super().__init__()
        self.vm_name = vm_name


class BaseDialog(Screen[T]):
    """A base class for dialogs with a cancel binding."""

    BINDINGS = [("escape", "cancel_modal", "Cancel")]

    def action_cancel_modal(self) -> None:
        """Cancel the modal dialog."""
        self.dismiss(None)

    @staticmethod
    def validate_name(name: str) -> str | None:
        """
        Validates a name to be alphanumeric with underscores, not hyphens.
        Returns an error message string if invalid, otherwise None.
        """
        if not name:
            return "Name cannot be empty."
        if not re.fullmatch(r"^[a-zA-Z0-9_]+$", name):
            return "Name must be alphanumeric and can contain underscores, but not hyphens."
        return None


class ConfirmationDialog(BaseDialog[bool]):
    """A dialog to confirm an action."""

    def __init__(self, prompt: str) -> None:
        super().__init__()
        self.prompt = prompt

    def compose(self):
        yield Vertical(
            Label(self.prompt, id="question"),
            Horizontal(
                Button("Yes", variant="error", id="yes", classes="dialog-buttons"),
                Button("No", variant="primary", id="no", classes="dialog-buttons"),
                id="dialog-buttons",
            ),
            id="dialog",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "yes":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_cancel_modal(self) -> None:
        """Cancel the modal."""
        self.dismiss(False)


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


class VMCard(Static):
    name = reactive("")
    status = reactive("")
    cpu = reactive(0)
    memory = reactive(0)
    vm = reactive(None)
    color = reactive("blue")

    cpu_history = reactive([])
    mem_history = reactive([])

    last_cpu_time = 0
    last_cpu_time_ts = 0

    def compose(self):
        with Vertical(id="info-container"):
            classes = ""
            yield Static(self.name, id="name", classes=classes)
            status_class = self.status.lower()
            yield Static(f"Status: {self.status}", id="status", classes=status_class)
            #cpu_mem_widget = Static(f"{self.cpu} VCPU | {self.memory} MB", id="cpu-mem-info", classes="cpu-mem-clickable")
            #cpu_mem_widget.styles.content_align = ("center", "middle")
            #yield cpu_mem_widget
            with Horizontal(id="cpu-sparkline-container", classes="sparkline-container"):
                cpu_spark = Static(f"{self.cpu} VCPU", id="cpu-mem-info", classes="sparkline-label")
                yield cpu_spark #Label(f"{self.cpu} VCPU:", classes="sparkline-label")
                yield Sparkline(self.cpu_history, id="cpu-sparkline")
            with Horizontal(id="mem-sparkline-container", classes="sparkline-container"):
                mem_gb = round(self.memory / 1024, 1)
                mem_spark = Static(f"{mem_gb} Gb", id="cpu-mem-info", classes="sparkline-label")
                yield mem_spark #Label(f"{self.memory}", classes="sparkline-label")
                yield Sparkline(self.mem_history, id="mem-sparkline")

            with TabbedContent(id="button-container"):
                with TabPane("Manage", id="manage-tab"):
                    with Horizontal():
                        with Vertical():
                            yield Button("Start", id="start", variant="success")
                            yield Button("Stop", id="stop", variant="error")
                            yield Static(classes="button-separator")
                            yield Button("Pause", id="pause", variant="primary")
                            yield Button("Resume", id="resume", variant="success")
                        with Vertical():
                            yield Button("View XML", id="xml")
                            yield Static(classes="button-separator")
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
                #with TabPane("Info", id="info-tab"):
                    #with Horizontal():
                    #    with Vertical():
                    #        yield Button( "Show info", id="info-button", variant="primary",)
                with TabPane("Special", id="special-tab"):
                    with Horizontal():
                        with Vertical():
                            yield Button("Delete", id="delete", variant="success", classes="delete-button")
                            yield Static(classes="button-separator")
                            yield Button("Clone", id="clone", variant="success", classes="clone-button")
                        with Vertical():
                            yield Button( "Show info", id="info-button", variant="primary")
                            yield Static(classes="button-separator")
                            yield Button( "Rename", id="rename-button", variant="primary", classes="rename-button")

    def on_mount(self) -> None:
        self.styles.background = self.color
        self.update_button_layout()
        self._update_status_styling()
        self.update_stats()  # Initial update
        self.timer = self.set_interval(5, self.update_stats)

    def on_unmount(self) -> None:
        """Stop the timer when the widget is removed."""
        self.timer.stop()

    def update_stats(self) -> None:
        """Update CPU and memory statistics."""
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

            except libvirt.libvirtError as e:
                logging.error(f"Error getting stats for {self.name}: {e}")
        
    def update_button_layout(self):
        """Update the button layout based on current VM status."""
        start_button = self.query_one("#start", Button)
        stop_button = self.query_one("#stop", Button)
        pause_button = self.query_one("#pause", Button)
        resume_button = self.query_one("#resume", Button)
        delete_button = self.query_one("#delete", Button)
        connect_button = self.query_one("#connect", Button)
        restore_button = self.query_one("#snapshot_restore", Button)
        snapshot_delete_button = self.query_one("#snapshot_delete", Button)
        info_button = self.query_one("#info-button", Button)
        clone_button = self.query_one("#clone", Button)
        rename_button = self.query_one("#rename-button", Button)
        cpu_sparkline_container = self.query_one("#cpu-sparkline-container")
        mem_sparkline_container = self.query_one("#mem-sparkline-container")


        is_stopped = self.status == "Stopped"
        is_running = self.status == "Running"
        is_paused = self.status == "Paused"
        has_snapshots = self.vm and self.vm.snapshotNum(0) > 0

        start_button.display = is_stopped
        stop_button.display = is_running or is_paused
        delete_button.display = is_running or is_paused or is_stopped
        clone_button.display = is_stopped
        rename_button.display = is_stopped
        pause_button.display = is_running
        resume_button.display = is_paused
        connect_button.display = is_running
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
                    self.vm.create()
                    self.status = "Running"
                    status_widget = self.query_one("#status")
                    status_widget.update(f"Status: {self.status}")
                    self._update_status_styling()
                    self.update_button_layout()
                    self.app.refresh_vm_list()
                    logging.info(f"Successfully started VM: {self.name}")
                    self.app.show_success_message(f"VM '{self.name}' started successfully.")
                except libvirt.libvirtError as e:
                    self.app.show_error_message(f"Error on VM {self.name} during 'start': {e}")

        elif event.button.id == "stop":
            logging.info(f"Attempting to stop VM: {self.name}")
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

        elif event.button.id == "pause":
            logging.info(f"Attempting to pause VM: {self.name}")
            if self.vm.isActive():
                try:
                    self.vm.suspend()
                    self.status = "Paused"
                    status_widget = self.query_one("#status")
                    status_widget.update(f"Status: {self.status}")
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
                status_widget.update(f"Status: {self.status}")
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
                        status_widget.update(f"Status: {self.status}")
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

            def on_confirm(confirmed: bool) -> None:
                if confirmed:
                    try:
                        if self.vm.isActive():
                            self.vm.destroy() # Shut down the VM first if it's active
                        self.vm.undefine() # Undefine the VM
                        self.app.show_success_message(f"VM '{self.name}' deleted successfully.")
                        self.app.refresh_vm_list()
                        logging.info(f"Successfully deleted VM: {self.name}")
                    except libvirt.libvirtError as e:
                        self.app.show_error_message(f"Error on VM {self.name} during 'delete VM': {e}")

            self.app.push_screen(
                ConfirmationDialog(f"Are you sure you want to delete VM '{self.name}'?"), on_confirm
            )

        elif event.button.id == "clone":
            logging.info(f"Attempting to clone VM: {self.name}")

            def handle_clone_name(new_name: str | None) -> None:
                if new_name:
                    try:
                        vm_info.clone_vm(self.vm, new_name)
                        self.app.show_success_message(f"VM '{self.name}' cloned as '{new_name}' successfully.")
                        self.app.refresh_vm_list()
                        logging.info(f"Successfully cloned VM '{self.name}' to '{new_name}'")
                    except Exception as e:
                        self.app.show_error_message(f"Error cloning VM {self.name}: {e}")

            self.app.push_screen(CloneNameDialog(), handle_clone_name)

        elif event.button.id == "rename-button":
            logging.info(f"Attempting to rename VM: {self.name}")

            def handle_rename(new_name: str | None) -> None:
                if not new_name:
                    return

                def do_rename(delete_snapshots=False):
                    try:
                        vm_info.rename_vm(self.vm, new_name, delete_snapshots=delete_snapshots)
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

        elif event.button.id == "info-button":
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
