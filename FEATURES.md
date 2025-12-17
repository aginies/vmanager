# Rainbow V Manager - Features

## Overview
Rainbow V Manager is a Textual-based TUI (Terminal User Interface) application for managing QEMU/KVM virtual machines using the libvirt Python API. It provides a comprehensive interface for VM management with features that go beyond basic management.

## Main Interface Features

### Multi-server Management
- Connect to multiple libvirt servers simultaneously
- Transhypervisor view showing VMs from different servers
- Server selection and management interface

### VM Grid Display
- VMs displayed in a responsive grid layout
- Color-coded status indicators (Running, Paused, Stopped)
- CPU and memory usage sparklines for running VMs
- Pagination controls for large VM lists (now defaults to page 1 if current page becomes empty after deletion)

### VM Management Actions
- Start, Shutdown, Force Off (destroy), Pause, Resume
- Delete VM with optional storage cleanup: Now more robust, always using libvirt API for managed storage volumes, preventing permission errors. Automatically deletes VM snapshot metadata.
- Clone VM functionality
- Rename VM with snapshot handling
- Take, restore, and delete VM snapshots
- View/Edit XML configuration
- Connect to VM via virt-viewer
- Web console access via novnc (when available)
  - When connecting to a remote libvirt server via SSH, the web console can be configured to run either locally (default) or directly on the remote server.
  - To enable running the web console on the remote server, set `REMOTE_WEBCONSOLE: True` in your `config.yaml`.
  - When `REMOTE_WEBCONSOLE` is enabled, `websockify` and `novnc` assets must be installed on the remote server at the paths specified in `config.yaml` (default: `/usr/bin/websockify` and `/usr/share/novnc/`).
  - For secure (HTTPS) remote web console access, `cert.pem` and `key.pem` files must also be present on the remote server in `~/.config/vmanager/`.
- Bulk actions on selected VMs (start, stop, force off, pause, delete): Now include a progress bar for long-running operations.

### Advanced Features
- Filter VMs by status (All, Running, Paused, Stopped) and search by name
- Server preferences configuration
- Virsh shell access
- Detailed VM information view
- Web console management with automatic port allocation
- Configuration file management for server lists
- Create new VMs (with single server connection)
- Bulk operations on multiple VMs

## Configure VM Features

### CPU Configuration
- Edit CPU count
- Select CPU model from available models (including host-passthrough and default options)
- CPU model selection is disabled when VM is running

### Memory Configuration
- Edit memory size in MB
- Enable/disable shared memory (disabled when VM is running)

### Firmware Configuration
- Select firmware type (BIOS or UEFI)
- For UEFI firmware:
  - Enable/disable Secure Boot
  - Enable/disable AMD-SEV and AMD-SEV-ES (when supported)
  - Select UEFI file from available options
- Machine type selection (disabled when VM is running)

### Boot Configuration
- Enable/disable boot menu
- Boot device management
- Set boot order for devices

### Disk Management
- View all disks in a table format
- Add new disk (create new or attach existing)
- Attach existing disk from storage pools
- Remove disk
- Disable disk
- Enable disk
- Edit disk properties (cache mode and discard mode)
- Disk status indicators (enabled/disabled)
- Set disk cache and discard modes

### Network Configuration
- View network interfaces with MAC addresses and IP addresses
- Change network interface to a different network
- View network DNS and gateway information
- Add new network interface
- Remove network interface
- Change network interface model

### VirtIO-FS Configuration
- View existing VirtIO-FS mounts
- Add new VirtIO-FS mount
- Edit existing VirtIO-FS mount
- Delete VirtIO-FS mount
- Requires shared memory to be enabled

### Video Configuration
- Select video model (virtio, qxl, vga, cirrus, bochs, ramfb, none, default)
- Video model selection is disabled when VM is running

### Graphics Configuration
- Select graphics type (VNC, Spice, or None)
- Configure listen type (Address or None)
- Set address (Hypervisor default, Localhost only, All interfaces)
- Enable/disable auto port allocation
- Set port number (when auto port is disabled)
- Enable/disable password protection
- Set password for graphics access
- Apply graphics settings (disabled when VM is running)
- When switching from Spice to VNC: If other SPICE-related devices (channels, audio, QXL video) are detected, the user is prompted to remove them for a clean switch. This process automatically removes SPICE channels and USB redirection, changes SPICE audio to 'none', and converts QXL video to 'virtio'. A default VNC graphics device is added if no other graphics device exists after removal.

### TPM Configuration
- Select TPM model (tpm-crb, tpm-tis, or none)
- Select TPM type (emulated or passthrough)
- Configure device path for passthrough TPM
- Configure backend type and path for passthrough TPM
- Apply TPM settings (disabled when VM is running)

### RNG Configuration
- Configure Random Number Generator (RNG) host device.
- Apply RNG settings (disabled when VM is running).

### Sound Configuration
- Select sound model (ac97, ich6, sb16, pcspk, es1370, hda, default)
- Sound model selection is disabled when VM is running

### Watchdog Configuration
- Configure Watchdog device for VM
- Set watchdog model and action (reset, shutdown, poweroff)
- Watchdog configuration is disabled when VM is running

### Input Configuration
- Configure input devices (keyboard, mouse, tablet)
- Set input device type and bus (usb, ps2, virtio)
- Input configuration is disabled when VM is running

### Additional Features
- Tabbed interface for organized configuration
- Toggle between main and extended configuration tabs
- Real-time status indicators
- Confirmation dialogs for destructive actions
- Error handling and user feedback
- VM status validation (prevents configuration changes when VM is running)

## Server Management Features

### Network Management
- View all networks in a table format
- Create new network with NAT or routed type
- Edit network properties including DHCP settings
- Delete network with confirmation
- Toggle network active state
- Toggle network autostart state
- View network XML details
- Get list of VMs using a specific network

### Storage Management
- View storage pools in a tree format
- Create new storage pool (directory or network file system)
- Delete storage pool with confirmation
- Create new storage volume
- Delete storage volume with confirmation
- Toggle storage pool active state
- Toggle storage pool autostart state
- List unused storage volumes
- Get all storage volumes across all pools

## User Interface Features

### Keyboard Shortcuts
- `v` - View Log
- `ctrl+v` - Virsh Shell
- `f` - Filter VM
- `p` - Server Pref
- `m` - Servers List
- `s` - Select Servers
- `ctrl+a` - Select/Deselect All VMs on current page
- `q` - Quit

### Visual Elements
- Color-coded server identification
- Status indicators with color coding (Running, Paused, Stopped)
- Sparkline graphs for CPU and memory usage
- Responsive layout that adapts to terminal size
- Tabbed interface for organized information display
- Selection indicators for multiple VMs

## Technical Capabilities

### Connection Management
- Support for multiple libvirt connection types (local, SSH, etc.)
- Automatic detection of virt-viewer, websockify, and novnc availability
- Error handling and logging
- Responsive UI that adapts to terminal size
- Command-line mode support (--cmd flag)

## User Experience
- Visual feedback through notifications
- Confirmation dialogs for destructive actions
- Loading indicators for long-running operations
- Detailed error messages
- Command-line mode for advanced users
- Bulk operations with improved progress indication
- Real-time VM status updates

## Warning
This project is part of a SUSE hackweek project, it's not mature, under heavy development, lacks a lot of features, and surely contains tons of bugs. You have been warned. Please report any bugs or ask for specific features.
