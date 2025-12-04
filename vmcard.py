from textual.widgets import Static, Button
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.message import Message
import subprocess
import tempfile
import libvirt
from xmlutil import get_vm_machine_firmware_info
from textual import on


class VMStateChanged(Message):
    """Posted when a VM's state changes."""


class VMStartError(Message):
    """Posted when a VM fails to start."""

    def __init__(self, vm_name: str, error_message: str) -> None:
        super().__init__()
        self.vm_name = vm_name
        self.error_message = error_message


class VMCard(Static):
    name = reactive("")
    status = reactive("")
    description = reactive("")
    cpu = reactive(0)
    memory = reactive(0)
    vm = reactive(None)
    color = reactive("blue")
    machine_type = reactive("")
    firmware = reactive("")

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
        show_machine_type: bool = True,
        show_firmware: bool = True,
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
        self.show_machine_type = show_machine_type
        self.show_firmware = show_firmware
        if self.vm:
            xml_content = self.vm.XMLDesc(0)
            info = get_vm_machine_firmware_info(xml_content)
            self.machine_type = info.get("machine_type", "N/A")
            self.firmware = info.get("firmware", "N/A")

    DEFAULT_CSS = """
    VMCard {
        width: auto;
        height: auto;
        min-height: 70;
        text-align: center;
        padding: 0 0;
    }
    #name {
        background: black;
        color: white;
        padding: 1 0;
        text-style: bold;
        content-align: center middle;
    }
    #name.running-name {
        background: green;
        color: black;
    }
    #name.paused-name {
        background:yellow;
        color: black;
    }
    #status {
        padding: 0 1;
        border: solid white;
        content-align: center middle;
    }
    #status.running {
        border: solid green;
    }
    #status.stopped {
        border: solid red;
    }
    #status.paused {
        border: solid yellow;
    }
    Button {
        width: 80%;
        height: 1;
        margin: 0 1;
        padding: 0 0;
    }
    #button-container {
        margin-top: 1;
    }
    """

    def compose(self):
        with Vertical(id="info-container"):
            if self.status == "Running":
                classes = "running-name"
            elif self.status == "Paused":
                classes = "paused-name"
            else:
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
            cpu_mem_widget = Static(f"CPU: {self.cpu} | Memory: {self.memory} MB")
            cpu_mem_widget.styles.content_align = ("center", "middle")
            yield cpu_mem_widget
            if (
                self.show_machine_type
                and self.machine_type
                and self.machine_type != "N/A"
            ):
                machine_type_widget = Static(f"{self.machine_type}")
                machine_type_widget.styles.content_align = ("center", "middle")
                yield machine_type_widget
            if self.show_firmware and self.firmware and self.firmware != "N/A":
                firmware_widget = Static(f"{self.firmware}")
                firmware_widget.styles.content_align = ("center", "middle")
                yield firmware_widget

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
                    name_widget = self.query_one("#name")
                    name_widget.remove_class("paused-name")
                    name_widget.add_class("running-name")
                    self.update_button_layout()
                    self.post_message(VMStateChanged())

                except libvirt.libvirtError as e:
                    self.post_message(
                        VMStartError(vm_name=self.name, error_message=str(e))
                    )
        elif event.button.id == "stop":
            if self.vm.isActive():
                self.vm.destroy()
                self.status = "Stopped"
                self.query_one("#status").update(f"Status: {self.status}")
                self.update_button_layout()
                self.post_message(VMStateChanged())
        elif event.button.id == "pause":
            if self.vm.isActive():
                self.vm.suspend()
                self.status = "Paused"
                status_widget = self.query_one("#status")
                status_widget.update(f"Status: {self.status}")
                status_widget.remove_class("running", "stopped")
                status_widget.add_class("paused")
                name_widget = self.query_one("#name")
                name_widget.remove_class("running-name")
                name_widget.add_class("paused-name")
                self.update_button_layout()
                self.post_message(VMStateChanged())
        elif event.button.id == "resume":
            self.vm.resume()
            self.status = "Running"
            status_widget = self.query_one("#status")
            status_widget.update(f"Status: {self.status}")
            status_widget.remove_class("stopped", "paused")
            status_widget.add_class("running")
            name_widget = self.query_one("#name")
            name_widget.remove_class("paused-name")
            name_widget.add_class("running-name")
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
