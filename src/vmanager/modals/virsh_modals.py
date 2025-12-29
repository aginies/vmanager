"""
Main interface
"""
import asyncio

from textual.app import ComposeResult
from textual.widgets import (
        Header, Footer, Input, Label,
        TextArea,
        )
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual import on

class VirshShellScreen(ModalScreen):
    """Screen for an interactive virsh shell."""

    BINDINGS = [
        ("escape", "app.pop_screen", "Close Shell"),
    ]

    def __init__(self, uri: str) -> None:
        super().__init__()
        self.uri = uri

    def compose(self) -> ComposeResult:
        with Vertical(id="virsh-shell-container"):
            yield Header()
            yield Label("Virsh Interactive Shell (esc to quit)", id="virsh-shell-title")
            yield Label("Note: This shell starts a new `virsh` process, which may require re-authentication for remote connections. Using SSH keys is recommended.", classes="virsh-shell-note")
            yield TextArea(
                id="virsh-output",
                read_only=True,
                show_line_numbers=False,
                classes="virsh-output-area"
            )
            with Horizontal(id="virsh-input-container"):
                #yield Label("virsh>")
                yield Input(
                    placeholder="Enter virsh command...",
                    id="virsh-command-input",
                    classes="virsh-input-field"
                )
            yield Footer()

    async def on_mount(self) -> None:
        self.virsh_process = None
        self.output_textarea = self.query_one("#virsh-output", TextArea)
        self.command_input = self.query_one("#virsh-command-input", Input)

        starting_virsh_text = "Starting virsh shell..."
        self.app.show_success_message(starting_virsh_text)

        try:
            uri = self.uri

            self.virsh_process = await asyncio.create_subprocess_exec(
                "/usr/bin/virsh", "-c", uri,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            self.output_textarea.text += f"Connected to: {uri}\n"

            self.read_stdout_task = asyncio.create_task(self._read_stream(self.virsh_process.stdout))
            self.read_stderr_task = asyncio.create_task(self._read_stream(self.virsh_process.stderr))

            self.command_input.focus()

        except FileNotFoundError:
            error_msg = "Error: 'virsh' command not found. Please ensure libvirt-client is installed."
            self.app.show_error_message(error_msg)
            self.command_input.disabled = True
        except Exception as e:
            error_msg = f"Error starting virsh: {e}"
            self.app.show_error_message(error_msg)
            self.command_input.disabled = True

    async def _read_stream(self, stream: asyncio.StreamReader) -> None:
        while True:
            try:
                data = await stream.read(4096)
                if not data:
                    break
                self.output_textarea.text += data.decode(errors='replace')
            except asyncio.CancelledError:
                break
            except Exception as e:
                reading_err_msg = f"Error reading from virsh: {e}"
                self.app.show_error_message(reading_err_msg)
                break

    @on(Input.Submitted, "#virsh-command-input")
    async def on_command_input_submitted(self, event: Input.Submitted) -> None:
        command = event.value.strip()
        self.command_input.value = ""
        if not command:
            return

        self.output_textarea.text += f"virsh> {command}\n"

        if self.virsh_process and self.virsh_process.stdin:
            try:
                self.virsh_process.stdin.write(command.encode() + b"\n")
                await self.virsh_process.stdin.drain()
            except Exception as e:
                error_msg = f"Error sending command: {e}"
                self.app.show_error_message(error_msg)
        else:
            error_msg = "Virsh process not running."
            self.app.show_error_message(error_msg)

        # Scroll to the end after writing output
        self.output_textarea.scroll_end()

    async def on_unmount(self) -> None:
        if self.read_stdout_task:
            self.read_stdout_task.cancel()
            await self.read_stdout_task
        if self.read_stderr_task:
            self.read_stderr_task.cancel()
            await self.read_stderr_task

        if self.virsh_process and self.virsh_process.returncode is None:
            self.virsh_process.terminate()
            await self.virsh_process.wait()
            tmsg = "Virsh shell terminated.\n"
            self.app.show_success_message(tmsg)
