# Virtui Manager

A powerful, text-based Terminal User Interface (TUI) application for managing QEMU/KVM virtual machines using the libvirt Python API. 

## Why Virtui Manager?

Managing virtual machines in a terminal environment has never been easier or more powerful. Virtui Manager bridges the gap between the simplicity of command-line tools and the rich functionality of GUI-based solutions, offering the best of both worlds for virtualization administrators.

### The Problem with Traditional Tools
- **Virt-manager** requires X11 forwarding, which is slow, resource-intensive, and often impossible in remote environments
- **GUI-based solutions** are heavy with X dependencies, making them unsuitable for headless servers or low-bandwidth connections
- **Command-line tools** lack the intuitive interface needed for complex VM management tasks

### Why Virtui Manager is Different
Virtui Manager solves these challenges with:
- **Lightweight Terminal Interface**: No X11 dependencies, works perfectly over SSH
- **Remote Management**: Efficient low-bandwidth control of remote libvirt servers
- **Rich Feature Set**: Advanced VM management capabilities in a simple, intuitive interface
- **Multi-server Support**: Manage VMs across multiple libvirt servers from a single interface
- **Performance Optimized**: Built-in caching reduces libvirt calls and improves responsiveness

## Key Features

### VM Management
- **Complete Lifecycle Control**: Start, shutdown, force off, pause, resume, and delete VMs
- **Advanced Operations**: Clone VMs with custom suffixes, bulk operations, snapshot management
- **Detailed Monitoring**: Real-time CPU, memory, disk, and network usage sparklines
- **Flexible Configuration**: Edit CPU, memory, firmware, boot, disk, network, and graphics settings and more

### Network & Storage Management
- **Network Operations**: Create, edit, and manage virtual networks
- **Storage Management**: Handle storage pools, volumes, and perform storage operations
- **VirtIO-FS Support**: Configure shared filesystems for enhanced VM performance

### Advanced Capabilities
- **Multi-server Management**: Connect to and manage multiple libvirt servers simultaneously
- **Bulk Operations**: Execute commands across multiple VMs at once
- **Web Console Access**: Integrated VNC support with novnc
- **Migration Support**: Live and offline VM migration capabilities
- **PCI Passthrough**: Support for hardware device passthrough

### User Experience
- **Intuitive TUI**: Color-coded status indicators, responsive layout, and visual feedback
- **Keyboard Shortcuts**: Efficient navigation and operations with customizable key bindings
- **Confirmation Dialogs**: Safety measures for destructive operations

## Who Is This For?

Virtui Manager is ideal for:
- **System Administrators** managing KVM virtualization environments
- **DevOps Engineers** requiring efficient VM management in CI/CD pipelines
- **Remote System Administrators** working in low-bandwidth environments
- **Cloud Operators** managing multiple hypervisor servers
- **IT Professionals** who prefer terminal-based tools for virtualization management

## Requirements

- **Recommended Minimal Terminal Size**: 34x92
- **Remote Connection**: SSH access to libvirt server (ssh-agent recommended)
- **Python 3.7+**
- **libvirt** with Python bindings
- **Python Dependencies**: textual, pyaml, libvirt-python
- **Optional**: virt-viewer, novnc, websockify for enhanced functionality

## Installation

### Clone the Repository
```bash
git clone https://github.com/aginies/virtui-manager.git
cd virtui-manager
```

### Install Python Dependencies
```bash
pip install libvirt-python textual pyaml
```

### Run the Application
```bash
cd src/vmanager
python3 vmanager.py
```

## Command-Line Interface

In addition to the main TUI application, `vmanager` provides a command-line interface (`vmanager_cmd.py`) for:
- Multi-server management
- Bulk VM operations
- Basic Storage management
- Advanced VM selection with regular expressions
- Tab autocompletion for enhanced usability

Launch the CLI with:
```bash
python3 vmanager_cmd.py
```
Or:
```bash
python3 vmanager.py --cmd
```

## Configuration

Virtui Manager uses a YAML configuration file for customization:
- **User-specific**: `~/.config/virtui-manager/config.yaml`
- **System-wide**: `/etc/virtui-manager/config.yaml`

The configuration file supports the following options:

### Server Configuration
- **servers**: List of libvirt server connections (default: `[{'name': 'Localhost', 'uri': 'qemu:///system'}]`)

### Web Console Settings
- **REMOTE_WEBCONSOLE**: Enable remote web console (default: `False`)
- **WC_PORT_RANGE_START**: Start port for websockify (default: 40000)
- **WC_PORT_RANGE_END**: End port for websockify (default: 40050)
- **websockify_path**: Path to the websockify binary (default: `/usr/bin/websockify`)
- **novnc_path**: Path to noVNC files (default: `/usr/share/novnc/`)

### VNC Settings
- **VNC_QUALITY**: VNC quality setting (0-10, default: 0)
- **VNC_COMPRESSION**: VNC compression level (default: `9`)

### Performance & Behavior
- **AUTOCONNECT_ON_STARTUP**: Automatically connect to the first configured server on application startup (default: `False`)
- **CACHE_TTL**: Time-to-live for VM metadata cache in seconds. Reduces `libvirt` calls. (default: `3`)

### Network & Sound Models

As there is no simple way to get **sound** and **network** model using libvirt API, the user can provides a list in his own configuration file. 

To get a list of model for a machine type you can use the **qemu** command line:
```bash
qemu-system-x86_64 -machine pc-q35-10.1 -audio  model=help
qemu-system-x86_64 -machine pc-q35-10.1 -net  model=help
```

User config parameters:
- **network_models**: List of allowed network models (default: `['virtio', 'e1000', 'e1000e', 'rtl8139', 'ne2k_pci', 'pcnet']`)
- **sound_models**: List of allowed sound models (default: `['none', 'ich6', 'ich9', 'ac97', 'sb16', 'usb']`)

### Example Configuration
```yaml
servers:
  - name: "Remote Server"
    uri: "qemu+ssh://user@remote-host/system"

REMOTE_WEBCONSOLE: true
WC_PORT_RANGE_START: 40000
WC_PORT_RANGE_END: 40050
VNC_QUALITY: 1
VNC_COMPRESSION: 9
network_models:
  - virtio
  - e1000
  - rtl8139
```

## License

This project is licensed under the GPL3 License.
