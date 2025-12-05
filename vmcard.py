from textual.widgets import Static, Button, Input, ListView, ListItem, Label, TabbedContent, TabPane, Markdown
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.message import Message
from textual.screen import Screen
import subprocess
import tempfile
import libvirt
import logging
from textual import on
from textual.events import Click

class VMNameClicked(Message):
    """Posted when a VM's name is clicked."""

    def __init__(self, vm_name: str) -> None:
        super().__init__()
        self.vm_name = vm_name


class VMCard(Static):
    name = reactive("")
    status = reactive("")
    cpu = reactive(0)
    memory = reactive(0)
    vm = reactive(None)
    color = reactive("blue")

    def compose(self):
        with Vertical(id="info-container"):
            classes = ""
            yield Static(self.name, id="name", classes=classes)
            status_class = self.status.lower()
            cpu_mem_widget = Static(f"{self.cpu} VCPU | {self.memory} MB", id="cpu-mem-info", classes="cpu-mem-clickable")
            cpu_mem_widget.styles.content_align = ("center", "middle")
            yield cpu_mem_widget
            yield Static(f"Status: {self.status}", id="status", classes=status_class)

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

    def on_mount(self) -> None:
        self.styles.background = self.color
        self.update_button_layout()
        self._update_status_styling()

    def update_button_layout(self):
        """Update the button layout based on current VM status."""
        start_button = self.query_one("#start", Button)
        stop_button = self.query_one("#stop", Button)
        pause_button = self.query_one("#pause", Button)
        resume_button = self.query_one("#resume", Button)
        connect_button = self.query_one("#connect", Button)
        restore_button = self.query_one("#snapshot_restore", Button)
        delete_button = self.query_one("#snapshot_delete", Button)

        is_stopped = self.status == "Stopped"
        is_running = self.status == "Running"
        is_paused = self.status == "Paused"
        has_snapshots = self.vm and self.vm.snapshotNum(0) > 0

        start_button.display = is_stopped
        stop_button.display = is_running or is_paused
        pause_button.display = is_running
        resume_button.display = is_paused
        connect_button.display = is_running
        restore_button.display = has_snapshots
        delete_button.display = has_snapshots

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
                    try:
                        snapshot = self.vm.snapshotLookupByName(snapshot_name, 0)
                        snapshot.delete(0)
                        self.app.show_success_message(f"Snapshot '{snapshot_name}' deleted successfully.")
                        self.update_button_layout()
                        logging.info(f"Successfully deleted snapshot '{snapshot_name}' for VM: {self.name}")
                    except libvirt.libvirtError as e:
                        self.app.show_error_message(f"Error on VM {self.name} during 'snapshot delete': {e}")

            self.app.push_screen(SelectSnapshotDialog(snapshots, "Select snapshot to delete:"), delete_snapshot)

        elif event.button.id == "delete_vm":
            logging.info(f"Attempting to delete VM: {self.name}")
            try:
                if self.vm.isActive():
                    self.vm.destroy() # Shut down the VM first if it's active
                self.vm.undefine() # Undefine the VM
                self.app.show_success_message(f"VM '{self.name}' deleted successfully.")
                self.app.refresh_vm_list()
                logging.info(f"Successfully deleted VM: {self.name}")
            except libvirt.libvirtError as e:
                self.app.show_error_message(f"Error on VM {self.name} during 'delete VM': {e}")

    @on(Click, "#cpu-mem-info")
    def on_click_cpu_mem_info(self) -> None:
        """Handle clicks on the CPU/Memory info part of the VM card."""
        self.post_message(VMNameClicked(vm_name=self.name))

class SnapshotNameDialog(Screen):
    """A dialog to ask for a snapshot name."""

    BINDINGS = [("escape", "cancel_modal", "Cancel")]
    CSS_PATH = "snapshot.css"

    def compose(self):
        yield Vertical(
            Label("Enter snapshot name:", id="question"),
            Input(placeholder="snapshot_name"),
            Vertical(
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
            self.dismiss(input_widget.value)
        else:
            self.dismiss(None)
    
    def action_cancel_modal(self) -> None:
        """Cancel the modal."""
        self.dismiss(None)


class SelectSnapshotDialog(Screen[str]):
    """A dialog to select a snapshot from a list."""

    BINDINGS = [("escape", "cancel_modal", "Cancel")]
    CSS_PATH = "snapshot.css"

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
    
    def action_cancel_modal(self) -> None:
        """Cancel the modal."""
        self.dismiss(None)
