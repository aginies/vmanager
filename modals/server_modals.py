"""
Server management 
"""
import logging
from typing import Tuple
from textual.app import ComposeResult
from textual.widgets import Button, Label, DataTable, Input
from textual.containers import ScrollableContainer, Horizontal, Vertical
from textual.screen import ModalScreen
from vmcard import ConfirmationDialog

from modals.base_modals import BaseModal

from config import save_config

class ConnectionModal(BaseModal[str | None]):

    def compose(self) -> ComposeResult:
        with Vertical(id="connection-dialog"):
            yield Label("Enter QEMU Connection URI:")
            yield Input(
                placeholder="qemu+ssh://user@host/system or qemu:///system",
                id="uri-input",
            )
            with Horizontal():
                yield Button("Connect", variant="primary", id="connect-btn", classes="Buttonpage")
                yield Button("Cancel", variant="default", id="cancel-btn", classes="Buttonpage")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "connect-btn":
            uri_input = self.query_one("#uri-input", Input)
            self.dismiss(uri_input.value)
        elif event.button.id == "cancel-btn":
            self.dismiss(None)


class AddServerModal(BaseModal[Tuple[str, str] | None]):

    def compose(self) -> ComposeResult:
        with Vertical(id="add-server-dialog"):
            yield Label("Add New Server")
            yield Input(placeholder="Server Name", id="server-name-input")
            yield Input(placeholder="qemu+ssh://user@host/system", id="server-uri-input")
            with Horizontal():
                yield Button("Save", variant="primary", id="save-btn", classes="Buttonpage")
                yield Button("Cancel", variant="default", id="cancel-btn", classes="Buttonpage")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            name_input = self.query_one("#server-name-input", Input)
            uri_input = self.query_one("#server-uri-input", Input)
            self.dismiss((name_input.value, uri_input.value))
        elif event.button.id == "cancel-btn":
            self.dismiss(None)

class EditServerModal(BaseModal[Tuple[str, str] | None]):

    def __init__(self, server_name: str, server_uri: str) -> None:
        super().__init__()
        self.server_name = server_name
        self.server_uri = server_uri

    def compose(self) -> ComposeResult:
        with Vertical(id="edit-server-dialog"):
            yield Label("Edit Server")
            yield Input(value=self.server_name, id="server-name-input")
            yield Input(value=self.server_uri, id="server-uri-input")
            with Horizontal():
                yield Button("Save", variant="primary", id="save-btn", classes="Buttonpage")
                yield Button("Cancel", variant="default", id="cancel-btn", classes="Buttonpage")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            name_input = self.query_one("#server-name-input", Input)
            uri_input = self.query_one("#server-uri-input", Input)
            self.dismiss((name_input.value, uri_input.value))
        elif event.button.id == "cancel-btn":
            self.dismiss(None)


class ServerManagementModal(ModalScreen):
    """Modal screen for managing servers."""

    BINDINGS = [("escape", "close_modal", "Close")]

    def __init__(self, servers: list) -> None:
        super().__init__()
        self.servers = servers
        self.selected_row = None

    def compose(self) -> ComposeResult:
        with Vertical(id="server-management-dialog"):
            yield Label("Server List Management", classes="server-list")
            with ScrollableContainer():
                yield DataTable(id="server-table")
            with Horizontal():
                yield Button("Add", id="add-server-btn", classes="add-button", variant="success")
                yield Button("Edit", id="edit-server-btn", disabled=True, classes="edit-button")
                yield Button("Delete", id="delete-server-btn", disabled=True, classes="delete-button")
            with Horizontal():
                yield Button("Connect", id="select-btn", variant="primary", disabled=True, classes="Buttonpage")
                yield Button("Custom URL", id="custom-conn-btn", classes="Buttonpage")
            #yield Button("Close", id="close-btn", classes="close-button")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        table.add_column("Name", key="name")
        table.add_column("URI", key="uri")
        for server in self.servers:
            table.add_row(server['name'], server['uri'], key=server['uri'])
        table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.selected_row = event.cursor_row
        self.query_one("#edit-server-btn").disabled = False
        self.query_one("#delete-server-btn").disabled = False
        self.query_one("#select-btn").disabled = False

    def _reload_table(self):
        table = self.query_one(DataTable)
        table.clear()
        for server in self.servers:
            table.add_row(server['name'], server['uri'], key=server['uri'])
        table.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-btn":
            self.dismiss(self.servers)
        elif event.button.id == "select-btn":
            self.dismiss(self.selected_row)
        elif event.button.id == "add-server-btn":
            def add_server_callback(result):
                if result:
                    name, uri = result
                    self.servers.append({'name': name, 'uri': uri})
                    self.app.config['servers'] = self.servers
                    save_config(self.app.config)
                    self._reload_table()
            self.app.push_screen(AddServerModal(), add_server_callback)
        elif event.button.id == "edit-server-btn" and self.selected_row is not None:
            server_to_edit = self.servers[self.selected_row]
            def edit_server_callback(result):
                if result:
                    new_name, new_uri = result
                    self.servers[self.selected_row]['name'] = new_name
                    self.servers[self.selected_row]['uri'] = new_uri
                    self.app.config['servers'] = self.servers
                    save_config(self.app.config)
                    self._reload_table()
            self.app.push_screen(EditServerModal(server_to_edit['name'], server_to_edit['uri']), edit_server_callback)
        elif event.button.id == "delete-server-btn" and self.selected_row is not None:
            server_to_delete = self.servers[self.selected_row]
            server_name_to_delete = server_to_delete['name']

            def on_confirm(confirmed: bool) -> None:
                if confirmed:
                    try:
                        del self.servers[self.selected_row]
                        self.app.config['servers'] = self.servers
                        save_config(self.app.config)
                        self._reload_table()
                        self.selected_row = None
                        self.query_one("#edit-server-btn").disabled = True
                        self.query_one("#delete-server-btn").disabled = True
                        self.app.show_success_message(f"Server '{server_name_to_delete}' deleted successfully.")
                        logging.info(f"Successfully deleted Server '{server_name_to_delete}'")
                    except Exception as e:
                        self.app.show_error_message(f"Error deleting server '{server_name_to_delete}': {e}")

            self.app.push_screen(
                ConfirmationDialog(f"Are you sure you want to delete Server;\n'{server_name_to_delete}'\nfrom list?"), on_confirm)

        elif event.button.id == "custom-conn-btn":
             def connection_callback(uri: str | None):
                 if uri:
                     self.dismiss(uri)
             self.app.push_screen(ConnectionModal(), connection_callback)


    def action_close_modal(self) -> None:
        """Close the modal."""
        self.dismiss(self.servers)
