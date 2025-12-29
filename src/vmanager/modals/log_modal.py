"""
Log function
"""
from textual.app import ComposeResult
from textual.widgets import Button, Label, TextArea
from textual.containers import Vertical, Horizontal

from modals.base_modals import BaseModal

class LogModal(BaseModal[None]):
    """ Modal Screen to show Log"""

    def __init__(self, log_content: str, title: str = "Log View") -> None:
        super().__init__()
        self.log_content = log_content
        self.title = title

    def compose(self) -> ComposeResult:
        with Vertical(id="text-show"):
            yield Label(self.title, id="title")
            text_area = TextArea()
            text_area.load_text(self.log_content)
            yield text_area
        with Horizontal():
            yield Button("Close", variant="default", id="cancel-btn", classes="Buttonpage")

    def on_mount(self) -> None:
        """Called when the modal is mounted."""
        text_area = self.query_one(TextArea)
        text_area.scroll_end()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
