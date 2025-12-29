"""
Modal to show how to use ssh-agent.
"""
from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal, ScrollableContainer
from textual.widgets import Button, Markdown
from textual import on
from modals.base_modals import BaseModal

HOW_TO_SSH_TEXT = """
# Using an SSH Agent for Passwordless Connections

Using an `ssh-agent` is the standard and most secure way to handle passphrase-protected SSH keys, allowing you to connect without repeatedly entering your passphrase.

### What is an SSH Agent?

An `ssh-agent` is a background program that securely stores your private SSH keys in memory. When you try to connect to a remote server, SSH can ask the agent for the key, and the agent provides it. You only need to "unlock" your key once.

---

### Step 1: Start the `ssh-agent`

On most modern desktop environments, an agent is often started automatically. If not, run this in your terminal:

```bash
eval "$(ssh-agent -s)"
```

> To make this permanent, add the command to your shell's startup file (e.g., `~/.bashrc` or `~/.zshrc`).

---

### Step 2: Add Your SSH Key to the Agent

Use the `ssh-add` command. If your key is in a default location (`~/.ssh/id_rsa`, etc.), you can just run:

```bash
ssh-add
```

If your key is elsewhere, specify the path to the **private key**:

```bash
ssh-add /path/to/your/private_key
```

You will be prompted for your key's passphrase **one time**.

To verify the key was added, list the agent's keys:
```bash
ssh-add -l
```
---

### Step 3: Connect

That's it! `Rainbow V Manager` will now use the agent to authenticate for any `qemu+ssh://` connections without any more prompts.

---

### SSH Compression for Performance

For connections over slower networks, enabling SSH compression can significantly improve performance. This is configured in your SSH client's configuration file.

To enable compression for a specific host, add the following to your `~/.ssh/config` file:

```
Host your_remote_host_name
  Compression yes
```

Replace `your_remote_host_name` with the actual hostname or IP address you use in your `qemu+ssh://` URI. If you want to enable compression for all SSH connections, you can use `Host *`.
"""

class HowToSSHModal(BaseModal[None]):
    """A modal to display instructions for using an ssh-agent."""

    def compose(self) -> ComposeResult:
        with Vertical(id="howto-ssh-dialog"):
            with ScrollableContainer(id="howto-ssh-content"):
                yield Markdown(HOW_TO_SSH_TEXT, id="howto-ssh-markdown")
            with Horizontal(id="dialog-buttons"):
                yield Button("Close", id="close-btn", variant="primary")

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        self.dismiss()
