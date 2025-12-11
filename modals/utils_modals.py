"""
DirectorySelectionModal
"""
import os
from textual.containers import Horizontal, Vertical
from textual.widgets import (
        Label, Button, DirectoryTree
        )
from textual.app import ComposeResult
from modals.base_modal import BaseModal

class DirectorySelectionModal(BaseModal[str | None]):
    """A modal screen for selecting a directory."""

    def __init__(self, path: str | None = None) -> None:
        super().__init__()
        self.start_path = path if path and os.path.isdir(path) else os.path.expanduser("~")
        self._selected_path: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="directory-selection-dialog"):
            yield Label("Select a Directory")
            yield DirectoryTree(self.start_path, id="dir-tree")
            with Horizontal():
                yield Button("Select", variant="primary", id="select-btn", disabled=True)
                yield Button("Cancel", variant="default", id="cancel-btn")

    def on_mount(self) -> None:
        self.query_one(DirectoryTree).focus()

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        self._selected_path = event.path
        self.query_one("#select-btn").disabled = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "select-btn":
            if self._selected_path:
                self.dismiss(str(self._selected_path))
        elif event.button.id == "cancel-btn":
            self.dismiss(None)
