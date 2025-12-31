# Virtui Manager

A Textual-based TUI (Terminal User Interface) application for managing QEMU/KVM virtual machines using the libvirt python API.

TUI is [Python Textual](https://github.com/Textualize/textual)

## Why

Virt-manager is only usable with X or X forward, and this is very slow and not possible in many cases to use it. It has a lot of X dependencies. 

This terminal solution is simple, very few deps, remote control with low bandwidth. Moreover it includes some features like disabling a disk (intead or removing it completly), change machine-type, Bulk operation, etc.... 

I developed some other Virtu related project like [pvirsh](https://github.com/aginies/pvirsh), [virt-scenario](https://github.com/aginies/virt-scenario), and most of their features will be integrated into this project too (some are already availables).

## Warning

Born during a **SUSE hackweek**, this project is a work-in-progress with potential bugs, and it still missing some features, and it is not fully tested. Development is also co-piloted by some AI agent for extra efficiency.

## Features

[Features](FEATURES.md)

## TODO

- Add all missing features on Adding/Removing stuff to VM
- Being able to create VM based on scenario usage: API is ready, just need to call from [virt-scenario](https://github.com/aginies/virt-scenario)

## Requirements

- Recomended Minimal terminal size: 34x92
- Remote connection to libvirt server ssh (ssh-agent recomended)
- Python 3.7+
- [libvirt](https://libvirt.org/)
- [textual](https://pypi.org/project/textual/)
- [pyaml](https://pypi.org/project/pyaml/)
- [virt-viewer](https://gitlab.com/virt-viewer/virt-viewer)

Optionnal:
- [novnc](https://novnc.com/noVNC/)
- [websockify](https://pypi.org/project/websockify/)

## Installation

### Clone this repository

```bash
git clone https://github.com/aginies/virtui-manager.git
```

```bash
cd src/vmanager
python3 vmanager.py
```

### Install Python dependencies

Get them from you Linux distribution, or using pip:
```bash
pip install libvirt-python textual pyaml
```

### Verify virt-viewer is available in PATH

```bash
which virt-viewer
```

## Command-Line Tool (vmanager_cmd.py)

In addition to the main TUI application, `vmanager` also provides a command-line interface (`vmanager_cmd.py`) for managing virtual machines and storage.

To launch the CLI, run:
```bash
python3 vmanager_cmd.py
```
Or:
```bash
python3 vmanager.py --cmd
```

## Configuration

The application uses a YAML configuration file to customize its behavior. The configuration file can be placed at:

- `~/.config/virtui-manager/config.yaml` (user-specific)
- `/etc/virtui-manager/config.yaml` (system-wide)

The default configuration is provided in `config.py`, and user configurations merge with these defaults. Here are the key configuration options:

- **WC_PORT_RANGE_START**: Start port for websockify (default: 40000)
- **WC_PORT_RANGE_END**: End port for websockify (default: 40050)
- **websockify_path**: Path to the websockify binary (default: `/usr/bin/websockify`)
- **novnc_path**: Path to noVNC files (default: `/usr/share/novnc/`)
- **REMOTE_WEBCONSOLE**: Enable remote web console (default: `False`)
- **VNC_QUALITY**: VNC quality setting (0-10, default: 0)
- **VNC_COMPRESSION**: VNC compression level (default: `9`)
- **AUTOCONNECT_ON_STARTUP**: Automatically connect to the first configured server on application startup (default: `False`)
- **CACHE_TTL**: Time-to-live for VM metadata cache in seconds. Reduces `libvirt` calls. (default: `3`)
- **network_models**: List of allowed network models (default: `['virtio', 'e1000', 'e1000e', 'rtl8139', 'ne2k_pci', 'pcnet']`)
- **sound_models**: List of allowed sound models (default: `['none', 'ich6', 'ich9', 'ac97', 'sb16', 'usb']`)
- **servers**: List of libvirt server connections (default: `[{'name': 'Localhost', 'uri': 'qemu:///system'}]`)

To customize, create a `config.yaml` file with the desired settings. For example:

```yaml
servers:
  - name: "Remote Server"
    uri: "qemu+ssh://user@remote-host/system"
```

## License

This project is licensed under the GPL3 License.
