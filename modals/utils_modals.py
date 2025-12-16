"""
Usefull Modal screen
"""
import os
from textual.containers import Horizontal, Vertical
from textual.widgets import (
        Label, Button, DirectoryTree, LoadingIndicator,
        Markdown, ProgressBar
        )
from textual.app import ComposeResult
from modals.base_modals import BaseModal, BaseDialog

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

class LoadingModal(BaseModal[None]):
    """A modal screen that displays a loading indicator."""

    BINDINGS = [] # Override BaseModal's bindings to prevent user dismissal with escape

    DEFAULT_CSS = """
    LoadingModal {
        align: center middle;
    }
    """

    def compose(self) -> ComposeResult:
        yield LoadingIndicator()

class ProgressModal(BaseModal[None]):
    """A modal that shows a progress bar for a long-running task."""
    BINDINGS = []

    def __init__(self, title: str = "Working...") -> None:
        super().__init__()
        self._title_text = title

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label(self._title_text, id="progress-title"),
            ProgressBar(total=100, show_eta=True, id="progress-bar"),
            id="progress-modal-container",
        )


class ConfirmationDialog(BaseDialog[bool]):
    """A dialog to confirm an action."""

    def __init__(self, prompt: str) -> None:
        super().__init__()
        self.prompt = prompt

    def compose(self):
        yield Vertical(
            Markdown(self.prompt, id="question"),
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
