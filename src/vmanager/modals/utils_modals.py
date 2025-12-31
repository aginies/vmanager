"""
Usefull Modal screen
"""
import os
import pathlib
from typing import Iterable
from textual.containers import Horizontal, Vertical
from textual.widgets import (
        Label, Button, DirectoryTree, LoadingIndicator,
        Markdown, ProgressBar, Log
        )
from textual.app import ComposeResult
from modals.base_modals import BaseModal, BaseDialog

class SafeDirectoryTree(DirectoryTree):
    """
    A DirectoryTree that excludes problematic paths like /proc, /sys, and /dev.
    """
    def filter_paths(self, paths: Iterable[pathlib.Path]) -> Iterable[pathlib.Path]:
        """Filters out blacklisted paths to prevent recursion and performance issues."""
        BLACKLIST = ("proc", "sys", "dev")
        return [p for p in paths if not any(part in BLACKLIST for part in p.parts)]

class DirectorySelectionModal(BaseModal[str | None]):
    """A modal screen for selecting a directory."""

    def __init__(self, path: str | None = None) -> None:
        super().__init__()
        self.start_path = path if path and os.path.isdir(path) else os.path.expanduser("~")
        self._selected_path: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="directory-selection-dialog"):
            yield Label("Select a Directory")
            yield SafeDirectoryTree(self.start_path, id="dir-tree")
            with Horizontal():
                yield Button("Select", variant="primary", id="select-btn", disabled=True)
                yield Button("Cancel", variant="default", id="cancel-btn")

    def on_mount(self) -> None:
        self.query_one(SafeDirectoryTree).focus()

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        self._selected_path = str(event.path)
        self.query_one("#select-btn").disabled = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "select-btn":
            if self._selected_path:
                self.dismiss(self._selected_path)
        elif event.button.id == "cancel-btn":
            self.dismiss(None)

class FileSelectionModal(BaseModal[str | None]):
    """A modal screen for selecting a file."""

    def __init__(self, path: str | None = None) -> None:
        super().__init__()
        start_dir = path if path and os.path.isdir(path) else os.path.dirname(path) if path else os.path.expanduser("/")
        if not os.path.isdir(start_dir):
             start_dir = os.path.expanduser("/")
        self.start_path = start_dir
        self._selected_path: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="file-selection-dialog", classes="file-selection-dialog"):
            yield Label("Select a File")
            yield SafeDirectoryTree(self.start_path, id="file-tree")
            with Horizontal():
                yield Button("Select", variant="primary", id="select-btn", disabled=True)
                yield Button("Cancel", variant="default", id="cancel-btn")

    def on_mount(self) -> None:
        self.query_one(SafeDirectoryTree).focus()

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        self._selected_path = str(event.path)
        self.query_one("#select-btn").disabled = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "select-btn":
            if self._selected_path:
                self.dismiss(self._selected_path)
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
    """A modal that shows a progress bar and logs for a long-running task."""

    BINDINGS = []

    def __init__(self, title: str = "Working...") -> None:
        super().__init__()
        self._title_text = title
        self._progress_bar: ProgressBar | None = None
        self._log: Log | None = None

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label(self._title_text, id="progress-title"),
            ProgressBar(total=100, show_eta=True, id="progress-bar"),
            Log(id="progress-log", classes="progress-log", auto_scroll=True),
            id="progress-modal-container",
        )

    def on_mount(self) -> None:
        """Called when the modal is mounted."""
        self._progress_bar = self.query_one(ProgressBar)
        self._log = self.query_one(Log)

    def update_progress(self, progress: float) -> None:
        """Updates the progress bar."""
        if self._progress_bar:
            self._progress_bar.update(progress=progress)

    def add_log(self, message: str) -> None:
        """Adds a message to the log."""
        if self._log:
            self._log.write_line(message)


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
