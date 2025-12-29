"""
Main interface
"""
from textual.app import ComposeResult, on
from textual.widgets import (
        Button, Label,
        Checkbox, Select
        )
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen

from modals.base_modals import BaseModal
from modals.utils_modals import LoadingModal
from connection_manager import ConnectionManager


class SelectServerModal(BaseModal[None]):
    """Screen to select servers to connect to."""

    def __init__(self, servers, active_uris, connection_manager: ConnectionManager):
        super().__init__()
        self.servers = servers
        self.active_uris = active_uris
        self.id_to_uri_map = {}
        self.connection_manager = connection_manager

    def sanitize_for_id(self, text: str) -> str:
        """Create a valid Textual ID from a string."""
        sanitized = 'server_' + ''.join(c if c.isalnum() else '_' for c in text)
        return sanitized

    def compose(self) -> ComposeResult:
        with Vertical(id="select-server-container", classes="info-details"):
            yield Label("Select Servers to Display")
            server_iter = iter(self.servers)
            with Vertical(classes="info-details"):
                for server1 in server_iter:
                    with Horizontal():
                        is_active1 = server1['uri'] in self.active_uris
                        sanitized_id1 = self.sanitize_for_id(server1['uri'])
                        self.id_to_uri_map[sanitized_id1] = server1['uri']
                        yield Checkbox(server1['name'], value=is_active1, id=sanitized_id1)
                        try:
                            server2 = next(server_iter)
                            is_active2 = server2['uri'] in self.active_uris
                            sanitized_id2 = self.sanitize_for_id(server2['uri'])
                            self.id_to_uri_map[sanitized_id2] = server2['uri']
                            yield Checkbox(server2['name'], value=is_active2, id=sanitized_id2)
                        except StopIteration:
                            pass # Handle odd number of servers

            with Horizontal(classes="button-details"):
                yield Button("Done", id="done-servers", variant="primary", classes="done-button")
                yield Button("Cancel", id="cancel-servers", classes="cancel-button")

    @on(Checkbox.Changed)
    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Handle checkbox changes to connect or disconnect from servers."""
        checkbox_id = str(event.checkbox.id)
        uri = self.id_to_uri_map.get(checkbox_id)

        if not uri:
            return

        if event.value:  # If checkbox is checked
            loading_modal = LoadingModal()
            self.app.push_screen(loading_modal)

            def connect_and_update():
                conn = self.app.vm_service.connect(uri)
                self.app.call_from_thread(loading_modal.dismiss)
                if conn is None:
                    self.app.call_from_thread(
                        self.app.show_error_message,
                        f"Failed to connect to {uri}"
                    )
                    # Revert checkbox state on failure
                    checkbox = self.query(f"#{checkbox_id}").first()
                    self.app.call_from_thread(setattr, checkbox, "value", False)
                else:
                    if uri not in self.active_uris:
                        self.active_uris.append(uri)

            self.app.worker_manager.run(
                connect_and_update, name=f"connect_server_{uri}"
            )
        else:  # If checkbox is unchecked
            # Disconnect from the server
            self.connection_manager.disconnect(uri)
            # Remove URI from active_uris if it exists
            if uri in self.active_uris:
                self.active_uris.remove(uri)

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "done-servers":
            self.dismiss(self.active_uris)
        elif event.button.id == "cancel-servers":
            self.dismiss(None)

class SelectOneServerModal(BaseModal[str]):
    def __init__(self, servers: list[dict], title: str = "Select a server", button_label: str = "Launch"):
        super().__init__()
        self.servers = servers
        self.server_options = [(s['name'], s['uri']) for s in servers]
        self.title_text = title
        self.button_label = button_label

    def compose(self) -> ComposeResult:
        with Vertical(id="select-one-server-container"):
            yield Label(self.title_text)
            yield Select(self.server_options, prompt="Select server...", id="server-select")
            yield Label("")
            with Horizontal():
                yield Button(self.button_label, id="launch-btn", variant="primary", disabled=True)
                yield Button("Cancel", id="cancel-btn")

    @on(Select.Changed, "#server-select")
    def on_server_select_changed(self, event: Select.Changed) -> None:
        self.query_one("#launch-btn", Button).disabled = not event.value

    @on(Button.Pressed, "#launch-btn")
    def on_launch_button_pressed(self) -> None:
        select = self.query_one("#server-select", Select)
        if select.value:
            self.dismiss(select.value)

    @on(Button.Pressed, "#cancel-btn")
    def on_cancel_button_pressed(self) -> None:
        self.dismiss()
