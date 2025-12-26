"""
Vmanager modals
"""
from textual.app import ComposeResult
from textual.message import Message
from textual.containers import ScrollableContainer, Horizontal, Vertical
from textual.widgets import (
        Button, Input, Label,
        ListView, ListItem, Checkbox, RadioButton,
        RadioSet
        )
from modals.base_modals import BaseModal


class FilterModal(BaseModal[None]):
    """Modal screen for selecting a filter."""

    class FilterChanged(Message):
        """Posted when the filter settings are applied."""
        def __init__(self, status: str, search: str) -> None:
            super().__init__()
            self.status = status
            self.search = search

    def __init__(self, current_search: str = "", current_status: str = "default") -> None:
        super().__init__()
        self.current_search = current_search
        self.current_status = current_status

    def compose(self) -> ComposeResult:
        with Vertical(id="filter-dialog"):
            yield Label("Filter by Name")
            with Vertical(classes="info-details"):
                yield Input(placeholder="Enter VM name...", id="search-input", value=self.current_search)
                with RadioSet(id="status-radioset"):
                    yield RadioButton("All", id="status_default", value=self.current_status == "default")
                    yield RadioButton("Running", id="status_running", value=self.current_status == "running")
                    yield RadioButton("Paused", id="status_paused", value=self.current_status == "paused")
                    yield RadioButton("Stopped", id="status_stopped", value=self.current_status == "stopped")
                    yield RadioButton("Manually Selected", id="status_selected", value=self.current_status == "selected")
            with Horizontal():
                yield Button("Apply", id="apply-btn", variant="success")
                yield Button("Cancel", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.app.pop_screen()
        elif event.button.id == "apply-btn":
            search_text = self.query_one("#search-input", Input).value
            radioset = self.query_one(RadioSet)
            status_button = radioset.pressed_button
            status = "default"
            if status_button:
                status = status_button.id.replace("status_", "")
            
            self.post_message(self.FilterChanged(status=status, search=search_text))
            self.app.pop_screen()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handles Enter key press in the search input."""
        # This implicitly acts as an "Apply" button press
        search_text = self.query_one("#search-input", Input).value
        radioset = self.query_one(RadioSet)
        status_button = radioset.pressed_button
        status = "default"
        if status_button:
            status = status_button.id.replace("status_", "")
        
        self.post_message(self.FilterChanged(status=status, search=search_text))
        self.app.pop_screen()

class CreateVMModal(BaseModal[dict | None]):
    """Modal screen for creating a new VM."""

    def compose(self) -> ComposeResult:
        with Vertical(id="create-vm-dialog"):
            yield Label("Create New VM")
            yield Input(placeholder="VM Name", id="vm-name-input", value="new_vm")
            yield Input(placeholder="Memory (MB, e.g., 2048)", id="vm-memory-input", value="2048")
            yield Input(placeholder="VCPU (e.g., 2)", id="vm-vcpu-input", value="2")
            yield Input(placeholder="Disk Image Path (e.g., /var/lib/libvirt/images/myvm.qcow2)", id="vm-disk-input", value="/var/lib/libvirt/images/new_vm.qcow2")
            # For simplicity, we won't add network details yet.
            with Horizontal():
                yield Button("Create", variant="primary", id="create-btn", classes="Buttonpage")
                yield Button("Cancel", variant="default", id="cancel-btn", classes="Buttonpage")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create-btn":
            name = self.query_one("#vm-name-input", Input).value
            memory = self.query_one("#vm-memory-input", Input).value
            vcpu = self.query_one("#vm-vcpu-input", Input).value
            disk = self.query_one("#vm-disk-input", Input).value
            self.dismiss({'name': name, 'memory': memory, 'vcpu': vcpu, 'disk': disk})
        elif event.button.id == "cancel-btn":
            self.dismiss(None)

class AddEditVirtIOFSModal(BaseModal[dict | None]):
    """Modal screen for adding or editing a VirtIO-FS mount."""

    def __init__(self, source_path: str = "", target_path: str = "", readonly: bool = False, is_edit: bool = False) -> None:
        super().__init__()
        self.source_path = source_path
        self.target_path = target_path
        self.readonly = readonly
        self.is_edit = is_edit

    def compose(self) -> ComposeResult:
        with Vertical(id="add-edit-virtiofs-dialog"):
            yield Label("Edit VirtIO-FS Mount" if self.is_edit else "Add VirtIO-FS Mount")
            yield Input(placeholder="Source Path (e.g., /mnt/share)", id="virtiofs-source-input", value=self.source_path)
            yield Input(placeholder="Target Path (e.g., /share)", id="virtiofs-target-input", value=self.target_path)
            yield Checkbox("Export filesystem as readonly mount", id="virtiofs-readonly-checkbox", value=self.readonly)
            with Horizontal():
                yield Button("Save" if self.is_edit else "Add", variant="primary", id="save-add-btn", classes="Buttonpage")
                yield Button("Cancel", variant="default", id="cancel-btn", classes="Buttonpage")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-add-btn":
            source_path = self.query_one("#virtiofs-source-input", Input).value
            target_path = self.query_one("#virtiofs-target-input", Input).value
            readonly = self.query_one("#virtiofs-readonly-checkbox", Checkbox).value

            if not source_path or not target_path:
                self.app.show_error_message("Source Path and Target Path cannot be empty.")
                return

            self.dismiss({'source_path': source_path, 'target_path': target_path, 'readonly': readonly})
        elif event.button.id == "cancel-btn":
            self.dismiss(None)

class EditCpuModal(BaseModal[str | None]):
    """Modal screen for editing VCPU count."""

    def __init__(self, current_cpu: str = "") -> None:
        super().__init__()
        self.current_cpu = current_cpu

    def compose(self) -> ComposeResult:
        with Vertical(id="edit-cpu-dialog", classes="edit-cpu-dialog"):
            yield Label("Enter new VCPU count")
            yield Input(placeholder="e.g., 2", id="cpu-input", type="integer", value=self.current_cpu)
            with Horizontal():
                yield Button("Save", variant="primary", id="save-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            cpu_input = self.query_one("#cpu-input", Input)
            self.dismiss(cpu_input.value)
        elif event.button.id == "cancel-btn":
            self.dismiss(None)


class EditMemoryModal(BaseModal[str | None]):
    """Modal screen for editing memory size."""

    def __init__(self, current_memory: str = "") -> None:
        super().__init__()
        self.current_memory = current_memory

    def compose(self) -> ComposeResult:
        with Vertical(id="edit-memory-dialog", classes="edit-memory-dialog"):
            yield Label("Enter new memory size (MB)")
            yield Input(placeholder="e.g., 2048", id="memory-input", type="integer", value=self.current_memory)
            with Horizontal():
                yield Button("Save", variant="primary", id="save-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            memory_input = self.query_one("#memory-input", Input)
            self.dismiss(memory_input.value)
        elif event.button.id == "cancel-btn":
            self.dismiss(None)
class SelectMachineTypeModal(BaseModal[str | None]):
    """Modal screen for selecting machine type."""

    def __init__(self, machine_types: list[str], current_machine_type: str = "") -> None:
        super().__init__()
        self.machine_types = machine_types
        self.current_machine_type = current_machine_type

    def compose(self) -> ComposeResult:
        with Vertical(id="select-machine-type-dialog", classes="select-machine-type-dialog"):
            yield Label("Select Machine Type:")
            with ScrollableContainer():
                yield ListView(
                    *[ListItem(Label(mt)) for mt in self.machine_types],
                    id="machine-type-list",
                    classes="machine-type-list"
                )
            with Horizontal():
                yield Button("Cancel", variant="default", id="cancel-btn")

    def on_mount(self) -> None:
        list_view = self.query_one(ListView)
        try:
            #self.query_one(DirectoryTree).focus()
            current_index = self.machine_types.index(self.current_machine_type)
            list_view.index = current_index
        except (ValueError, IndexError):
            pass

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.dismiss(str(event.item.query_one(Label).renderable))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
