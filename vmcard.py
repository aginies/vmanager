from textual.widgets import Static, Button
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.message import Message
import subprocess
import tempfile
import libvirt
from textual import on


class VMStateChanged(Message):
    """Posted when a VM's state changes."""


class VMStartError(Message):
    """Posted when a VM fails to start."""

    def __init__(self, vm_name: str, error_message: str) -> None:
        super().__init__()
        self.vm_name = vm_name
        self.error_message = error_message

class VMNameClicked(Message):
    """Posted when a VM's name is clicked."""

    def __init__(self, vm_name: str) -> None:
        super().__init__()
        self.vm_name = vm_name

class VMCard(Static):
    name = reactive("")
    status = reactive("")
    description = reactive("")
    cpu = reactive(0)
    memory = reactive(0)
    vm = reactive(None)
    color = reactive("blue")

    def __init__(
        self,
        name: str = "",
        status: str = "",
        description: str = "",
        cpu: int = 0,
        memory: int = 0,
        vm=None,
        color: str = "blue",
        show_description: bool = True,
    ) -> None:
        super().__init__()
        self.name = name
        self.status = status
        self.description = description
        self.cpu = cpu
        self.memory = memory
        self.vm = vm
        self.color = color
        self.show_description = show_description
        if self.vm:
            xml_content = self.vm.XMLDesc(0)


    def compose(self):
        with Vertical(id="info-container"):
            classes = ""
            yield Static(self.name, id="name", classes=classes)
            status_class = self.status.lower()
            yield Static(f"Status: {self.status}", id="status", classes=status_class)
            if (
                self.show_description
                and self.description
                and self.description != "No description"
            ):
                yield Static(f"Description: {self.description}")
            cpu_mem_widget = Static(f"VCPU: {self.cpu} | Memory: {self.memory} MB")
            cpu_mem_widget.styles.content_align = ("center", "middle")
            yield cpu_mem_widget

            with Horizontal(id="button-container"):
                with Vertical():
                    if self.status == "Stopped":
                        yield Button("Start", id="start", variant="success")
                    elif self.status == "Running":
                        yield Button("Stop", id="stop", variant="error")
                        yield Button("Pause", id="pause", variant="primary")
                    elif self.status == "Paused":
                        yield Button("Stop", id="stop", variant="error")
                        yield Button("Resume", id="resume", variant="success")
                with Vertical():
                    yield Button("View XML", id="xml")
                    if self.status == "Running":
                        yield Button("Connect", id="connect", variant="default")

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
        elif self.status == "Paused":
            left_vertical.mount(Button("Stop", id="stop", variant="error"))
            left_vertical.mount(Button("Resume", id="resume", variant="success"))

        right_vertical.mount(Button("View XML", id="xml"))
        if self.status == "Running":
            right_vertical.mount(Button("Connect", id="connect", variant="default"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start":
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

                except libvirt.libvirtError as e:
                    self.post_message(
                        VMStartError(vm_name=self.name, error_message=str(e))
                    )
                    # Ensure header is updated on an error
                    if hasattr(self, "app") and self.app:
                        self.app.update_header()
        elif event.button.id == "stop":
            if self.vm.isActive():
                self.vm.destroy()
                self.status = "Stopped"
                self.query_one("#status").update(f"Status: {self.status}")
                self.update_button_layout()
                self.post_message(VMStateChanged())
                # Ensure header is updated after VM state change
                if hasattr(self, "app") and self.app:
                    self.app.update_header()
        elif event.button.id == "pause":
            if self.vm.isActive():
                self.vm.suspend()
                self.status = "Paused"
                status_widget = self.query_one("#status")
                status_widget.update(f"Status: {self.status}")
                status_widget.remove_class("running", "stopped")
                status_widget.add_class("paused")
                self.update_button_layout()
                self.post_message(VMStateChanged())
        elif event.button.id == "resume":
            self.vm.resume()
            self.status = "Running"
            status_widget = self.query_one("#status")
            status_widget.update(f"Status: {self.status}")
            status_widget.remove_class("stopped", "paused")
            status_widget.add_class("running")
            self.update_button_layout()
            self.post_message(VMStateChanged())
        elif event.button.id == "xml":
            xml_content = self.vm.XMLDesc(0)
            with tempfile.NamedTemporaryFile(
                mode="w+", delete=False, suffix=".xml"
            ) as tmpfile:
                tmpfile.write(xml_content)
                tmpfile.flush()
                with self.app.suspend():
                    subprocess.run(["view", tmpfile.name])
        elif event.button.id == "connect":
            with self.app.suspend():
                subprocess.run(
                    ["virt-viewer", "--connect", "qemu:///system", self.name]
                )

    def on_click(self) -> None:
        """Handle clicks on the entire VM card."""
        self.post_message(VMNameClicked(vm_name=self.name))
