# Rainbow V Manager

A Textual-based TUI (Terminal User Interface) application for managing QEMU/KVM virtual machines.

## Overview

This project provides a terminal-based interface to manage virtual machines using libvirt. It consists of two main components:

- `tui.py`: The main terminal user interface application
- `vmcard.py`: A widget component for displaying VM information and controls

## Features

- List and manage QEMU/KVM virtual machines
- Start, stop, pause, and resume VMs
- View VM details (status, CPU, memory, description, machine type, firmware)
- Connect to VMs using virt-viewer
- View VM XML configuration
- Change connection URI
- **Snapshot management (take, restore, delete)**
- **Dynamic footer for status and error messages**
- **View application log file**

## Requirements

- Python 3.7+
- libvirt-python
- textual
- virt-viewer (for connecting to VMs)

## Installation

```bash
# Install Python dependencies
pip install libvirt-python textual

# Verify virt-viewer is available in PATH
which virt-viewer
```

### Main Interface

When you run the application, you'll see:

1. **Header**: Shows connection information and VM statistics:
   - Total VMs count
   - Running, paused, and stopped VMs count
   - Current connection URI

2. **Top Controls**: Provides global actions and filtering options:
   - "Connection" button to change the connection URI
   - "View Log" button to open the application's error log file
   - Filter menu to sort VMs by status (All, Running, Paused, Stopped)

3. **VM Cards**: Each VM is displayed in a card with:
   - VM name (with color-coded status)
   - Status (Running, Paused, Stopped)
   - CPU and Memory usage
   - Description (if available)
   - Machine type (if available)
   - Firmware (if available)
   - Action buttons (Start, Stop, Pause, Resume, Take Snapshot, Restore Snapshot, Delete Snapshot, View XML, Connect)

### Available Actions

- **Start**: Start a stopped VM
- **Stop**: Stop a running VM
- **Pause**: Pause a running VM
- **Resume**: Resume a paused VM
- **Take Snapshot**: Create a new snapshot of the VM.
- **Restore Snapshot**: Revert the VM to a previously taken snapshot.
- **Delete Snapshot**: Delete an existing snapshot.
- **View XML**: Display the VM's XML configuration in a temporary file
- **Connect**: Launch virt-viewer to connect to the VM
- **View Log**: Open the `vm_manager_error.log` file for inspection.

### Connection Management

To change the connection URI:
1. Select "Connection" from the top controls.
2. Enter a QEMU connection URI (e.g., `qemu+ssh://user@host/system` or `qemu:///system`)
3. Click "Connect"

## Components

### vmcard.py

This file contains the `VMCard` class, which is a Textual widget for displaying individual VM information and controls:
- Displays VM name with status color coding
- Shows status with colored border
- Shows CPU and memory usage
- Displays description, machine type, and firmware (if available)
- Provides action buttons based on VM current status, **including snapshot management**
- Handles VM state change events **and features a two-column button layout for running VMs**

### tui.py

This file contains the main `VMManagerTUI` class which implements the application:
- Main Textual application for managing VMs
- Connection management through modal dialogs
- VM listing and display in a grid layout
- State change handling for VMs
- Error handling for connection and VM operations
- Handles snapshot error and success messages, displaying them in a dynamically resizing footer.
- Display options for showing/hiding VM details
- Provides functionality to view the application's error log file.
- Errors during connection or VM operations are logged to `vm_manager_error.log` for later review.

### vm_info.py

This module contains utility functions (`get_vm_info`, `get_status`, `get_vm_description`, etc.) responsible for extracting detailed information about virtual machines from `libvirt` domain objects and their XML configurations. It parses various aspects like status, CPU, memory, firmware, machine type, network interfaces, disk information, and other attached devices.

### Styling (CSS Files)

The application uses several CSS files for styling different components:
- `tui.css`: Provides overall styling for the main application layout and general widgets.
- `vmcard.css`: Contains specific styles for the `VMCard` widget, defining its appearance.
- `snapshot.css`: Manages the styling for the `SnapshotNameDialog` and `SelectSnapshotDialog` modal screens.

## License

This project is licensed under the GPL3 License.
