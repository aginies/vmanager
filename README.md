# Rainbow V Manager

A Textual-based TUI (Terminal User Interface) application for managing QEMU/KVM virtual machines.

## Overview

This project provides a terminal-based interface to manage virtual machines using libvirt. It consists of two main components:

- `tui.py`: The main terminal user interface application
- `vmcard.py`: A widget component for displaying VM information and controls

## Media

- ![Screenshot](https://paste.opensuse.org/pastes/c93a4c1c71a8/raw)
- [Demo Video](https://www.youtube.com/watch?v=QIyAPAloU-k)

## Features

- User configuration file in **~/.config/vmanager/config.yaml**
- List and manage QEMU/KVM virtual machines
- Start, stop, pause, and resume VMs
- View VM details (status, CPU, memory, description, machine type, firmware, devices, etc...)
- Connect to VMs using **virt-viewer**
- View VM XML configuration
- Connection URI
- Manage a Server list
- Filter view 
- Snapshot management (take, restore, delete)
- Dynamic error messages
- View application log file

## Requirements

- Python 3.7+
- libvirt-python
- textual
- pyaml
- virt-viewer (for connecting to VMs)

## Installation

Clone this repository:
```bash
git clone https://github.com/aginies/vmanager.git
```

Install needed python lib:
```bash
# Install Python dependencies
pip install libvirt-python textual pyaml

# Verify virt-viewer is available in PATH
which virt-viewer
```

### Main Interface

When you run the application, you'll see:

1. **Header**: Shows connection information and VM statistics:
   - Total VMs count
   - Current connection URI

2. **Top Controls**: Provides global actions and filtering options:
   - **Connection** button to change the connection URI
   - **Manage Servers**: Server management list, add, edit, delete
   - **Select Server**: connect to a server in the list
   - **View Log** button to open the application's error log file
   - **Filter menu** to sort VMs by status (All, Running, Paused, Stopped)

3. **VM Cards**: Each VM is displayed in a card with:
   - VM name (with color-coded status)
   - Status (Running, Paused, Stopped)
   - CPU and Memory
   - Action buttons (Start, Stop, Pause, Resume, Take/Restore/Delete Snapshot, View XML, Connect)
   - Click on the card give you readable info about the VM configuration

4. **Footer**: show all shortcuts available

### Available Actions

- **Start**: Start a stopped VM
- **Stop**: Stop a running VM
- **Pause**: Pause a running VM
- **Resume**: Resume a paused VM
- **Take Snapshot**: Create a new snapshot of the VM.
- **Restore Snapshot**: Revert the VM to a previously taken snapshot.
- **Delete Snapshot**: Delete an existing snapshot.
- **View XML**: Display the VM's XML configuration in a temporary file
- **Connect**: Launch virt-viewer to connect to the VM (launched in a non-blocking external process).
- **View Log**: Open the `vm_manager.log` file for inspection.

### Connection Management

To change the connection URI:
1. Select "Connection" from the top controls.
2. Enter a QEMU connection URI (e.g., `qemu+ssh://user@host/system` or `qemu:///system`)
3. Click "Connect"

## TODO

- Support adding devices to VM
- Being able to create VM based on scenario usage

## License

This project is licensed under the GPL3 License.
