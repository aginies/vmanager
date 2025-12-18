# Rainbow V Manager

A Textual-based TUI (Terminal User Interface) application for managing QEMU/KVM virtual machines using the libvirt python API.

This is using Python Textual: https://github.com/Textualize/textual

## Why

Virt-manager is only usable with X or X forward, and this is very slow and not possible in many cases to use it,. It has a lot of dependencies.

This terminal solution is simple, very few deps, remote control with low bandwidth. Moreover it includes some features like disabling a disk (intead or removing it completly), change machine-type. Some other will be implemented later.

## Warning

This project is part of a SUSE **hackweek** project, its not mature, under heavy developement, its lacks a lot of features, and surely contains tons of bugs. You have been warned. Please report any bugs or ask for specific features.

## Features

[Features](FEATURES.md)

## TODO

- Add all missing features on Adding/Removing stuff to VM
- Being able to create VM based on scenario usage: API is ready, just need to call it (https://github.com/aginies/virt-scenario)

## Requirements

- Minimal terminal size: 34x92
- Remote connection to libvirt server ssh needs an SSH key copy to server! (ssh-copy-id with no password)
- Python 3.7+
- [libvirt](https://libvirt.org/)
- [textual](https://pypi.org/project/textual/)
- [pyaml](https://pypi.org/project/pyaml/)
- [virt-viewer](https://gitlab.com/virt-viewer/virt-viewer)
- [novnc](https://novnc.com/noVNC/)
- [websockify](https://pypi.org/project/websockify/)

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

## Configuration

The application uses a YAML configuration file to customize its behavior. The configuration file can be placed at:

- `~/.config/vmanager/config.yaml` (user-specific)
- `/etc/vmanager/config.yaml` (system-wide)

The default configuration is provided in `config.py`, and user configurations merge with these defaults. Here are the key configuration options:

- **WC_PORT_RANGE_START**: Start port for websockify (default: 40000)
- **WC_PORT_RANGE_END**: End port for websockify (default: 40050)
- **websockify_path**: Path to the websockify binary (default: `/usr/bin/websockify`)
- **novnc_path**: Path to noVNC files (default: `/usr/share/novnc/`)
- **REMOTE_WEBCONSOLE**: Enable remote web console (default: `False`)
- **VNC_QUALITY**: VNC quality setting (0-10, default: 0)
- **VNC_COMPRESSION**: VNC compression level (default: 9)
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
