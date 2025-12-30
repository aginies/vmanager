"""
Modals for input device configuration.
"""
from textual.widgets import Select, Button, Label
from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from modals.base_modals import BaseModal

class AddInputDeviceModal(BaseModal[None]):
    """A modal for adding a new input device."""

    def __init__(self, available_types: list, available_buses: list):
        super().__init__()
        self.available_types = available_types
        self.available_buses = available_buses

    def compose(self) -> ComposeResult:
        with Vertical(id="add-input-container"):
            yield Label("Input Device")
            yield Select(
                [(t, t) for t in self.available_types],
                prompt="Input Type",
                id="input-type-select",
            )
            yield Select(
                [(b, b) for b in self.available_buses],
                prompt="Bus",
                id="input-bus-select",
            )
            with Vertical():
                with Horizontal():
                    yield Button("Add", variant="primary", id="add-input")
                    yield Button("Cancel", variant="default", id="cancel-input")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add":
            input_type = self.query_one("#input-type-select", Select).value
            input_bus = self.query_one("#input-bus-select", Select).value
            if input_type and input_bus:
                self.dismiss({"type": input_type, "bus": input_bus})
            else:
                self.dismiss()
        else:
            self.dismiss()
