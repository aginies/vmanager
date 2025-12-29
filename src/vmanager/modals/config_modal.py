"""
Modal for user configuration
"""
from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal, ScrollableContainer
from textual import on
from textual.widgets import Label, Button, Input, Checkbox, Static

from config import save_config, get_user_config_path
from modals.base_modals import BaseModal

class ConfigModal(BaseModal[None]):
    """Modal screen for configuring the application."""

    def __init__(self, config: dict) -> None:
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        with ScrollableContainer(id="config-dialog"):
            yield Label("Application Configuration", id="config-title")
            yield Static(f"Editing: {get_user_config_path()}", classes="config-path-label")
            with ScrollableContainer():
                # Autoconnect on startup
                yield Checkbox(
                    "Autoconnect on startup",
                    self.config.get("AUTOCONNECT_ON_STARTUP", False),
                    id="autoconnect-checkbox",
                    tooltip="Automatically connect to the first configured server on application startup"
                )

                # Performance settings
                yield Label("Performance", classes="config-section-label")
                yield Label("Cache TTL (seconds):")
                yield Input(
                    value=str(self.config.get("CACHE_TTL", 1)),
                    id="cache-ttl-input",
                    type="integer",
                    tooltip="Time-to-live for VM metadata cache in seconds. Reduces libvirt calls."
                )

                # Web console settings
                yield Label("Web Console (novnc)", classes="config-section-label")
                yield Checkbox(
                    "Enable remote web console",
                    self.config.get("REMOTE_WEBCONSOLE", False),
                    id="remote-webconsole-checkbox",
                    tooltip="Enable secure SSH and noVNC remote viewing for headless server environments"
                )
                yield Label("Websockify Path:")
                yield Input(
                    value=self.config.get("websockify_path", "/usr/bin/websockify"),
                    id="websockify-path-input",
                    tooltip="Path to the websockify binary"
                )
                yield Label("noVNC Path:")
                yield Input(
                    value=self.config.get("novnc_path", "/usr/share/novnc/"),
                    id="novnc-path-input",
                    tooltip="Path to noVNC files"
                )
                with Horizontal(classes="port-range-container"):
                    yield Label("Websockify Port Range:", classes="port-range-label")
                    yield Input(
                        value=str(self.config.get("WC_PORT_RANGE_START", 40000)),
                        id="wc-port-start-input",
                        type="integer",
                        classes="port-range-input",
                        tooltip="Start port for websockify"
                    )
                    yield Input(
                        value=str(self.config.get("WC_PORT_RANGE_END", 40050)),
                        id="wc-port-end-input",
                        type="integer",
                        classes="port-range-input",
                        tooltip="End port for websockify"
                    )
                with Vertical():
                    with Horizontal():
                        yield Label("VNC Quality (0-9):")
                        yield Input(
                            value=str(self.config.get("VNC_QUALITY", 0)),
                            id="vnc-quality-input",
                            type="integer",
                            tooltip="VNC quality setting (0-9)"
                        )
                    with Horizontal():
                        yield Label("VNC Compression (0-9):")
                        yield Input(
                            value=str(self.config.get("VNC_COMPRESSION", 9)),
                            id="vnc-compression-input",
                            type="integer",
                            tooltip="VNC compression level (0-9)"
                        )

        with Horizontal():
            yield Button("Save", variant="primary", id="save-config-btn")
            yield Button("Cancel", variant="default", id="cancel-btn")

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-config-btn":
            try:
                self.config["AUTOCONNECT_ON_STARTUP"] = self.query_one("#autoconnect-checkbox", Checkbox).value
                self.config["REMOTE_WEBCONSOLE"] = self.query_one("#remote-webconsole-checkbox", Checkbox).value
                self.config["websockify_path"] = self.query_one("#websockify-path-input", Input).value
                self.config["novnc_path"] = self.query_one("#novnc-path-input", Input).value
                self.config["WC_PORT_RANGE_START"] = int(self.query_one("#wc-port-start-input", Input).value)
                self.config["WC_PORT_RANGE_END"] = int(self.query_one("#wc-port-end-input", Input).value)
                self.config["VNC_QUALITY"] = int(self.query_one("#vnc-quality-input", Input).value)
                self.config["VNC_COMPRESSION"] = int(self.query_one("#vnc-compression-input", Input).value)
                self.config["CACHE_TTL"] = int(self.query_one("#cache-ttl-input", Input).value)

                save_config(self.config)
                self.app.show_success_message("Configuration saved successfully.")
                self.dismiss(self.config)
            except Exception as e:
                self.app.show_error_message(f"Error saving configuration: {e}")
        elif event.button.id == "cancel-btn":
            self.dismiss(None)
