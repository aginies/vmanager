# Rainbow V Manager

A Textual-based TUI (Terminal User Interface) application for managing QEMU/KVM virtual machines using the libvirt python API.

## Overview

This project provides a terminal-based interface to manage virtual machines using libvirt.
This project is part of a SUSE **hackweek** project, its not mature, under heavy developement, so
its **risky** to use it.

## Media

![Screenshot](https://paste.opensuse.org/pastes/3e82e8b12deb/raw)
![Screenshot](https://paste.opensuse.org/pastes/2b6dd3fb59dd/raw)
![Screenshot](https://paste.opensuse.org/pastes/a894f2825956/raw)
![Screenshot](https://paste.opensuse.org/pastes/09eefc77fd9d/raw)
![Screenshot](https://paste.opensuse.org/pastes/370d17b6f927/raw)
![Screenshot](https://paste.opensuse.org/pastes/87e5465e718b/raw)
![Screenshot](https://paste.opensuse.org/pastes/cf8a73ab2a99/raw)
[Demo Video](https://www.youtube.com/watch?v=r49KpUghUI4)

## Features

General capabilities:
- List and manage QEMU/KVM Virtual Machines
- Dynamic error messages
- Direct virsh command on the server connected
- User configuration file for server list in **~/.config/vmanager/config.yaml**

## Requirements

- Python 3.7+
- libvirt-python
- textual
- pyaml
- virt-viewer (for connecting to VMs)

## Installation

### Clone this repository

```bash
git clone https://github.com/aginies/vmanager.git
```

### Install Python dependencies

```bash
pip install libvirt-python textual pyaml
```

### Verify virt-viewer is available in PATH

```bash
which virt-viewer
```

## Main Interface

When you run the application, you'll see:

1. **Header**: Shows connection information and VM:
   - Total VMs count
   - Current connection URI

2. **Top Controls**: Provides global actions and filtering options:
   - **Server Pref** configure network and storage (WIP)
   - **Server List**: Server management list, add, edit, delete
   - **Select Server**: connect to a server in the list, or via input
   - **Filter VM** to sort VMs by name and status (All, Running, Paused, Stopped)
   - **View Log** button to open the application's error log file

3. **VM Cards**: Each VM is displayed in a card with:
   - VM name
   - color-coded Status (Running, Paused, Stopped)
   - CPU and Mem Graph if running
   - Action buttons
   - in the VM details view
     - you can add/delete/disable disks
     - you can edit CPU/Mem/Machine type

4. **Footer**: show all shortcuts available

### Available Actions Buttons on VM cards

- **Start**: Start a stopped VM
- **Stop**: Stop a running VM
- **Pause**: Pause a running VM
- **Resume**: Resume a paused VM
- **Delete**: Delete a VM
- **Take Snapshot**: Create a new snapshot of the VM.
- **Restore Snapshot**: Revert the VM to a previously taken snapshot.
- **Delete Snapshot**: Delete an existing snapshot.
- **View XML**: Display the VM's XML configuration in a temporary file
- **Connect**: Launch virt-viewer to connect to the VM (launched in a non-blocking external process).
- **Clone**: Clone the current VM selected
- **Rename**: Rename the current VM
- **Show Info**: Get some info about the VM

### Connection Management

To change the connection URI:
1. Select "Select Server" from the top controls.
2. Clicl on "Custom URL"
3. Enter a QEMU connection URI (e.g., `qemu+ssh://user@host/system` or `qemu:///system`)
4. Click "Connect"

## TODO

- Support adding devices to VM
- Being able to create VM based on scenario usage

## License

This project is licensed under the GPL3 License.
