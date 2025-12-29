"""
virtiofs modals
"""
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
        Button, Input, Label, Checkbox,
        )
from modals.base_modals import BaseModal

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
