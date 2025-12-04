# VM Manager

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
- Toggle display options for VM information

## Requirements

- Python 3.7+
- libvirt-python
- textual
- virt-viewer (for connecting to VMs)

## Installation

```bash
# Install Python dependencies
pip install libvirt-python textual

## Usage

### Running the Application

```bash
python tui.py
```

### Main Interface

When you run the application, you'll see:

1. **Header**: Shows connection information and VM statistics:
   - Total VMs count
   - Running, paused, and stopped VMs count
   - Current connection URI

2. **Select Menu**: Allows you to:
   - Show All/Hide All VM details
   - Toggle Description, Machine Type, and Firmware display
   - Change connection URI

3. **VM Cards**: Each VM is displayed in a card with:
   - VM name (with color-coded status)
   - Status (Running, Paused, Stopped)
   - CPU and Memory usage
   - Description (if available)
   - Machine type (if available)
   - Firmware (if available)
   - Action buttons (Start, Stop, Pause, Resume, View XML, Connect)

### Available Actions

- **Start**: Start a stopped VM
- **Stop**: Stop a running VM
- **Pause**: Pause a running VM
- **Resume**: Resume a paused VM
- **View XML**: Display the VM's XML configuration in a temporary file
- **Connect**: Launch virt-viewer to connect to the VM

### Connection Management

To change the connection URI:
1. Select "Change Connection" from the dropdown menu
2. Enter a QEMU connection URI (e.g., `qemu+ssh://user@host/system` or `qemu:///system`)
3. Click "Connect"

## Components

### vmcard.py

This file contains the `VMCard` class, which is a Textual widget for displaying individual VM information and controls:
- Displays VM name with status color coding
- Shows status with colored border
- Shows CPU and memory usage
- Displays description, machine type, and firmware (if available)
- Provides action buttons based on VM current status
- Handles VM state change events

### tui.py

This file contains the main `VMManagerTUI` class which implements the application:
- Main Textual application for managing VMs
- Connection management through modal dialogs
- VM listing and display in a grid layout
- State change handling for VMs
- Error handling for connection and VM operations
- Display options for showing/hiding VM details

## License

This project is licensed under the GPL3 License.
