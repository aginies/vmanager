"""
Maange the configuration of the tool
"""
import os
from pathlib import Path
import yaml

#    'VMS_PER_PAGE': 4,
DEFAULT_CONFIG = {
    'AUTOCONNECT_ON_STARTUP': False,
    'WC_PORT_RANGE_START': 40000,
    'WC_PORT_RANGE_END': 40050,
    'websockify_path': '/usr/bin/websockify',
    'novnc_path': '/usr/share/novnc/',
    'REMOTE_WEBCONSOLE': False,
    'VNC_QUALITY': 0,
    'VNC_COMPRESSION': 9,
    'network_models': ["virtio", "e1000", "e1000e", "rtl8139", "ne2k_pci", "pcnet"],
    'sound_models': ["none", "ich6", "ich9", "ac97", "sb16", "usb"],
    'servers': [
        {'name': 'Localhost', 'uri': 'qemu:///system'},
    ],
}

def get_config_paths():
    """Returns the potential paths for the config file."""
    return [
        Path.home() / '.config' / 'vmanager' / 'config.yaml',
        Path('/etc') / 'vmanager' / 'config.yaml'
    ]

def get_user_config_path():
    """Returns the path to the user's config file."""
    return get_config_paths()[0]

def load_config():
    """
    Loads the configuration from the first found config file.
    If no config file is found, returns the default configuration.
    Merges the loaded configuration with default values to ensure all keys are present.
    """
    config_paths = get_config_paths()
    config_path = None
    user_config = {}

    for path in config_paths:
        if path.exists():
            config_path = path
            break

    if config_path:
        with open(config_path, 'r') as f:
            user_config = yaml.safe_load(f) or {}

    # Start with default config and update with user's config
    config = DEFAULT_CONFIG.copy()
    if user_config:
        config.update(user_config)
        # If user sets a value to null in yaml, it becomes None. Revert to default.
        for key, value in config.items():
            if value is None and key in DEFAULT_CONFIG:
                config[key] = DEFAULT_CONFIG[key]


    # Ensure 'servers' key exists and is a non-empty list
    if not isinstance(config.get('servers'), list) or not config.get('servers'):
        config['servers'] = DEFAULT_CONFIG['servers']

    return config

def save_config(config):
    """Saves the configuration to the user's config file."""
    config_path = get_config_paths()[0]  # Save to user's config
    os.makedirs(config_path.parent, exist_ok=True)
    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)
