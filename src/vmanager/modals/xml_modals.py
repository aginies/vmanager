"""
XML Display and Edit Modal
"""
from textual.app import ComposeResult
from textual.widgets import Button, TextArea
from textual.containers import Vertical, Horizontal
from modals.base_modals import BaseModal

class XMLDisplayModal(BaseModal[str | None]):
    """A modal screen for displaying and editing XML."""

    def __init__(self, xml_content: str, read_only: bool = False):
        super().__init__()
        self.xml_content = xml_content
        self.read_only = read_only

    def compose(self) -> ComposeResult:
        with Vertical(id="xml-display-dialog"):
            yield TextArea(
                self.xml_content,
                language="xml",
                show_line_numbers=True,
                read_only=self.read_only,
                theme="monokai",
                id="xml-textarea"
            )
            with Vertical(id="dialog-buttons"):
                with Horizontal():
                    if not self.read_only:
                        yield Button("Save", variant="primary", id="save-btn")
                    yield Button("Close", id="close-btn")

    def on_mount(self) -> None:
        self.query_one(TextArea).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            textarea = self.query_one("#xml-textarea", TextArea)
            self.dismiss(textarea.text)
        elif event.button.id == "close-btn":
            self.dismiss(None)
