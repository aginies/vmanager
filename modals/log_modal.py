"""
Log function
"""
from textual.app import ComposeResult
from textual.widgets import Button, Label, TextArea
from textual.containers import Vertical, Horizontal

from modals.base_modal import BaseModal

class LogModal(BaseModal[None]):
    """ Modal Screen to show Log"""

    def compose(self) -> ComposeResult:
        with Vertical(id="text-show"):
            yield Label("Log View", id="title")
            log_file = "vm_manager.log"
            text_area = TextArea()
            text_area.load_text(open(log_file, "r").read())
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
