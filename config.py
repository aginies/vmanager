import os
import yaml
from pathlib import Path

DEFAULT_CONFIG = {
    'VMS_PER_PAGE': 4,
    'servers': [
        {'name': 'Localhost', 'uri': 'qemu:///system'},
    ]
}

def get_config_paths():
    """Returns the potential paths for the config file."""
    return [
        Path.home() / '.config' / 'vmanager' / 'config.yaml',
        Path('/etc') / 'vmanager' / 'config.yaml'
    ]

def load_config():
    """
    Loads the configuration from the first found config file.
    If no config file is found, creates a default one.
    """
    config_paths = get_config_paths()
    config_path = None

    for path in config_paths:
        if path.exists():
            config_path = path
            break

    if config_path:
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    else:
        # No config file found, create a default one
        default_path = config_paths[0]
        os.makedirs(default_path.parent, exist_ok=True)
        with open(default_path, 'w') as f:
            yaml.dump(DEFAULT_CONFIG, f, default_flow_style=False)
        return DEFAULT_CONFIG

def save_config(config):
    """Saves the configuration to the user's config file."""
    config_path = get_config_paths()[0]  # Save to user's config
    os.makedirs(config_path.parent, exist_ok=True)
    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)

