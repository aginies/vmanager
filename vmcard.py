from textual.widgets import Static, Button, Input, ListView, ListItem, Label
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


class VMStateChanged(Message):
    """Posted when a VM's state changes."""


class VMStartError(Message):
    """Posted when a VM fails to start."""

    def __init__(self, vm_name: str, error_message: str) -> None:
        super().__init__()
        self.vm_name = vm_name
        self.error_message = error_message


class SnapshotError(Message):
    """Posted when a snapshot operation fails."""

    def __init__(self, vm_name: str, error_message: str) -> None:
        super().__init__()
        self.vm_name = vm_name
        self.error_message = error_message


class SnapshotSuccess(Message):
    """Posted when a snapshot operation succeeds."""

    def __init__(self, vm_name: str, message: str) -> None:
        super().__init__()
        self.vm_name = vm_name
        self.message = message


class VMActionError(Message):
    """Posted when a generic VM action fails."""

    def __init__(self, vm_name: str, action: str, error_message: str) -> None:
        super().__init__()
        self.vm_name = vm_name
        self.action = action
        self.error_message = error_message


class VMActionSuccess(Message):
    """Posted when a generic VM action succeeds."""

    def __init__(self, vm_name: str, action: str, message: str) -> None:
        super().__init__()
        self.vm_name = vm_name
        self.action = action
        self.message = message


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

    def __init__(
        self,
        name: str = "",
        status: str = "",
        cpu: int = 0,
        memory: int = 0,
        vm=None,
        color: str = "blue",
    ) -> None:
        super().__init__()
        self.name = name
        self.status = status
        self.cpu = cpu
        self.memory = memory
        self.vm = vm
        self.color = color
        if self.vm:
            xml_content = self.vm.XMLDesc(0)

    def compose(self):
        with Vertical(id="info-container"):
            classes = ""
            yield Static(self.name, id="name", classes=classes)
            status_class = self.status.lower()
            cpu_mem_widget = Static(f"{self.cpu} VCPU | {self.memory} MB", id="cpu-mem-info", classes="cpu-mem-clickable")
            cpu_mem_widget.styles.content_align = ("center", "middle")
            yield cpu_mem_widget
            yield Static(f"Status: {self.status}", id="status", classes=status_class)

            with Horizontal(id="button-container"):
                with Vertical():
                    if self.status == "Stopped":
                        yield Button("Start", id="start", variant="success")
                    elif self.status == "Running":
                        yield Button("Stop", id="stop", variant="error")
                        yield Button("Pause", id="pause", variant="primary")
                        yield Static(classes="button-separator")
                        yield Button("Snapshot", id="snapshot_take", variant="primary")
                    elif self.status == "Paused":
                        yield Button("Stop", id="stop", variant="error")
                        yield Button("Resume", id="resume", variant="success")
                with Vertical():
                    yield Button("View XML", id="xml")
                    if self.status == "Running":
                        yield Button("Connect", id="connect", variant="default")
                    if self.vm and self.vm.snapshotNum(0) > 0:
                        yield Static(classes="button-separator")
                        yield Button(
                            "Restore Snapshot",
                            id="snapshot_restore",
                            variant="primary",
                        )
                        yield Button(
                            "Del Snapshot",
                            id="snapshot_delete",
                            variant="error",
                        )
                        #yield Static(classes="button-separator")
                        #yield Button("Delete VM", id="delete_vm", variant="error")

    def on_mount(self) -> None:
        self.styles.background = self.color

    def update_button_layout(self):
        """Update the button layout based on current VM status."""
        # Remove existing buttons and recreate them
        button_container = self.query_one("#button-container")
        button_container.remove_children()
        left_vertical = Vertical()
        right_vertical = Vertical()

        button_container.mount(left_vertical)
        button_container.mount(right_vertical)

        if self.status == "Stopped":
            left_vertical.mount(Button("Start", id="start", variant="success"))
        elif self.status == "Running":
            left_vertical.mount(Button("Stop", id="stop", variant="error"))
            left_vertical.mount(Button("Pause", id="pause", variant="primary"))
            left_vertical.mount(Static(classes="button-separator"))
            left_vertical.mount(Button("Take Snapshot", id="snapshot_take", variant="primary"))
        elif self.status == "Paused":
            left_vertical.mount(Button("Stop", id="stop", variant="error"))
            left_vertical.mount(Button("Resume", id="resume", variant="success"))

        right_vertical.mount(Button("View XML", id="xml"))
        if self.status == "Running":
            right_vertical.mount(Button("Connect", id="connect", variant="default"))
        if self.vm and self.vm.snapshotNum(0) > 0:
            right_vertical.mount(Static(classes="button-separator"))
            right_vertical.mount(
                Button("Restore Snapshot", id="snapshot_restore", variant="primary")
            )
            right_vertical.mount(
                Button("Delete Snapshot", id="snapshot_delete", variant="error")
            )
            #right_vertical.mount(Static(classes="button-separator"))
            #right_vertical.mount(Button("Delete VM", id="delete_vm", variant="error"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start":
            logging.info(f"Attempting to start VM: {self.name}")
            if not self.vm.isActive():
                try:
                    self.vm.create()
                    self.status = "Running"
                    status_widget = self.query_one("#status")
                    status_widget.update(f"Status: {self.status}")
                    status_widget.remove_class("stopped", "paused")
                    status_widget.add_class("running")
                    self.update_button_layout()
                    self.post_message(VMStateChanged())
                    logging.info(f"Successfully started VM: {self.name}")
                    self.post_message(
                        VMActionSuccess(
                            vm_name=self.name, action="start", message=f"VM '{self.name}' started successfully."
                        )
                    )
                except libvirt.libvirtError as e:
                    self.post_message(
                        VMStartError(vm_name=self.name, error_message=str(e))
                    )

        elif event.button.id == "stop":
            logging.info(f"Attempting to stop VM: {self.name}")
            if self.vm.isActive():
                try:
                    self.vm.destroy()
                    self.status = "Stopped"
                    self.query_one("#status").update(f"Status: {self.status}")
                    self.update_button_layout()
                    self.post_message(VMStateChanged())
                    logging.info(f"Successfully stopped VM: {self.name}")
                    self.post_message(
                        VMActionSuccess(
                            vm_name=self.name, action="stop", message=f"VM '{self.name}' stopped successfully."
                        )
                    )
                except libvirt.libvirtError as e:
                    self.post_message(
                        VMActionError(vm_name=self.name, action="stop", error_message=str(e))
                    )

        elif event.button.id == "pause":
            logging.info(f"Attempting to pause VM: {self.name}")
            if self.vm.isActive():
                try:
                    self.vm.suspend()
                    self.status = "Paused"
                    status_widget = self.query_one("#status")
                    status_widget.update(f"Status: {self.status}")
                    status_widget.remove_class("running", "stopped")
                    status_widget.add_class("paused")
                    self.update_button_layout()
                    self.post_message(VMStateChanged())
                    logging.info(f"Successfully paused VM: {self.name}")
                    self.post_message(
                        VMActionSuccess(
                            vm_name=self.name, action="pause", message=f"VM '{self.name}' paused successfully."
                        )
                    )
                except libvirt.libvirtError as e:
                    self.post_message(
                        VMActionError(vm_name=self.name, action="pause", error_message=str(e))
                    )
        elif event.button.id == "resume":
            logging.info(f"Attempting to resume VM: {self.name}")
            try:
                self.vm.resume()
                self.status = "Running"
                status_widget = self.query_one("#status")
                status_widget.update(f"Status: {self.status}")
                status_widget.remove_class("stopped", "paused")
                status_widget.add_class("running")
                self.update_button_layout()
                self.post_message(VMStateChanged())
                logging.info(f"Successfully resumed VM: {self.name}")
                self.post_message(
                    VMActionSuccess(
                        vm_name=self.name, action="resume", message=f"VM '{self.name}' resumed successfully."
                    )
                )
            except libvirt.libvirtError as e:
                self.post_message(
                    VMActionError(vm_name=self.name, action="resume", error_message=str(e))
                )
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
                self.post_message(
                    VMActionError(vm_name=self.name, action="view XML", error_message=str(e))
                )
        elif event.button.id == "connect":
            logging.info(f"Attempting to connect to VM: {self.name}")
            try:
                subprocess.Popen(
                    ["virt-viewer", "--connect", self.app.connection_uri, self.name],
                )
                logging.info(f"Successfully launched virt-viewer for VM: {self.name}")
            except (FileNotFoundError, subprocess.CalledProcessError) as e:
                self.post_message(
                    VMActionError(vm_name=self.name, action="connect", error_message=str(e))
                )
        elif event.button.id == "snapshot_take":
            logging.info(f"Attempting to take snapshot for VM: {self.name}")
            def handle_snapshot_name(name: str | None) -> None:
                if name:
                    xml = f"<domainsnapshot><name>{name}</name></domainsnapshot>"
                    try:
                        self.vm.snapshotCreateXML(xml, 0)
                        self.post_message(
                            SnapshotSuccess(
                                vm_name=self.name,
                                message=f"Snapshot '{name}' created successfully.",
                            )
                        )
                        self.update_button_layout()
                    except libvirt.libvirtError as e:
                        self.post_message(
                            SnapshotError(vm_name=self.name, error_message=str(e))
                        )

            self.app.push_screen(SnapshotNameDialog(), handle_snapshot_name)

        elif event.button.id == "snapshot_restore":
            logging.info(f"Attempting to restore snapshot for VM: {self.name}")
            snapshots = self.vm.listAllSnapshots(0)
            if not snapshots:
                self.post_message(
                    SnapshotError(
                        vm_name=self.name, error_message="No snapshots to restore."
                    )
                )
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
                        status_widget.remove_class("running", "stopped", "paused")
                        status_widget.add_class(self.status.lower())
                        self.update_button_layout()

                        self.post_message(VMStateChanged())
                        self.post_message(
                            VMActionSuccess(
                                vm_name=self.name,
                                action="snapshot restore",
                                message=f"Restored to snapshot '{snapshot_name}' successfully.",
                            )
                        )
                        logging.info(f"Successfully restored snapshot '{snapshot_name}' for VM: {self.name}")
                    except libvirt.libvirtError as e:
                        self.post_message(
                            VMActionError(vm_name=self.name, action="snapshot restore", error_message=str(e))
                        )

            self.app.push_screen(SelectSnapshotDialog(snapshots, "Select snapshot to restore:"), restore_snapshot)

        elif event.button.id == "snapshot_delete":
            logging.info(f"Attempting to delete snapshot for VM: {self.name}")
            snapshots = self.vm.listAllSnapshots(0)
            if not snapshots:
                self.post_message(
                    VMActionError(
                        vm_name=self.name, action="snapshot delete", error_message="No snapshots to delete."
                    )
                )
                return

            def delete_snapshot(snapshot_name: str | None) -> None:
                if snapshot_name:
                    try:
                        snapshot = self.vm.snapshotLookupByName(snapshot_name, 0)
                        snapshot.delete(0)
                        self.post_message(
                            VMActionSuccess(
                                vm_name=self.name,
                                action="snapshot delete",
                                message=f"Snapshot '{snapshot_name}' deleted successfully.",
                            )
                        )
                        self.update_button_layout()
                        logging.info(f"Successfully deleted snapshot '{snapshot_name}' for VM: {self.name}")
                    except libvirt.libvirtError as e:
                        self.post_message(
                            VMActionError(vm_name=self.name, action="snapshot delete", error_message=str(e))
                        )

            self.app.push_screen(SelectSnapshotDialog(snapshots, "Select snapshot to delete:"), delete_snapshot)

        elif event.button.id == "delete_vm":
            logging.info(f"Attempting to delete VM: {self.name}")
            try:
                if self.vm.isActive():
                    self.vm.destroy() # Shut down the VM first if it's active
                self.vm.undefine() # Undefine the VM
                self.post_message(
                    VMActionSuccess(
                        vm_name=self.name, action="delete VM", message=f"VM '{self.name}' deleted successfully."
                    )
                )
                self.post_message(VMStateChanged()) # Refresh the VM list
                logging.info(f"Successfully deleted VM: {self.name}")
            except libvirt.libvirtError as e:
                self.post_message(
                    VMActionError(vm_name=self.name, action="delete VM", error_message=str(e))
                )

    @on(Click, "#cpu-mem-info")
    def on_click_cpu_mem_info(self) -> None:
        """Handle clicks on the CPU/Memory info part of the VM card."""
        self.post_message(VMNameClicked(vm_name=self.name))

class SnapshotNameDialog(Screen):
    """A dialog to ask for a snapshot name."""

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


class SelectSnapshotDialog(Screen[str]):
    """A dialog to select a snapshot from a list."""

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
