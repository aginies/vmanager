# Rainbow V Manager

A Textual-based TUI (Terminal User Interface) application for managing QEMU/KVM virtual machines using the libvirt python API.

This is using Python Textual: https://github.com/Textualize/textual

## Why

Virt-manager is only usable with X or X forward, and this is very slow and not possible in many cases to use it,. It has a lot of dependencies.

This terminal solution is simple, very few deps, remote control with low bandwidth. Moreover it includes some features like disabling a disk (intead or removing it completly), change machine-type. Some other will be implemented later.

## Warning

This project is part of a SUSE **hackweek** project, its not mature, under heavy developement, its lacks a lot of features, and surely contains tons of bugs. You have been warned. Please report any bugs or ask for specific features.

## Media

![Screenshot](https://paste.opensuse.org/pastes/a81e4dcd5c35/raw)
![Screenshot](https://paste.opensuse.org/pastes/54611f2dc75a/raw)
![Screenshot](https://paste.opensuse.org/pastes/dfb48c4390b5/raw)
![Screenshot](https://paste.opensuse.org/pastes/37d250075470/raw)
![Screenshot](https://paste.opensuse.org/pastes/c31c9cf0ee2c/raw)
![Screenshot](https://paste.opensuse.org/pastes/b596408544c0/raw)
![Screenshot](https://paste.opensuse.org/pastes/a37c655832a8/raw)
![Screenshot](https://paste.opensuse.org/pastes/54a634950a79/raw)
[Demo Video](https://www.youtube.com/watch?v=r49KpUghUI4)

## Features

General capabilities:
- List VM in a grid with management capabilities (QEMU/KVM Virtual Machines)
- Dynamic error/info messages
- virsh command console possible
- User configuration file for server list in **~/.config/vmanager/config.yaml**

## TODO

- Fix CSS issue (there is a lot as this is not trivial to deal with CSS...)
- Add all missing features on Adding/Removing stuff to VM
- Being able to create VM based on scenario usage: API is ready, just need to call it (https://github.com/aginies/virt-scenario)
- vmanager command console with CMD, launch command on "pattern" selected VM
- transhypervisor view, connected to multiple server

## Requirements

- Minimal terminal size: 34x92
- Python 3.7+
- libvirt
- textual
- pyaml
- virt-viewer (for connecting to VMs)

## Installation

### Clone this repository

```bash
git clone https://github.com/aginies/vmanager.git
```

```bash
python3 vmanager.py
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
   - **Server Pref** configure network and storage
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
- **Configure**: Configure the VM

### Connection Management

To change the connection URI:
1. Select "Select Server" from the top controls.
2. Clicl on "Custom URL"
3. Enter a QEMU connection URI (e.g., `qemu+ssh://user@host/system` or `qemu:///system`)
4. Click "Connect"


## License

This project is licensed under the GPL3 License.
