"""
Utils functions
"""
import logging
from functools import wraps
import socket
import subprocess
from pathlib import Path
import shutil
import os
from typing import List, Tuple, Union


def find_free_port(start: int, end: int) -> int:
    """
    Find a free port in the specified range.

    Args:
        start (int): Starting port number
        end (int): Ending port number

    Returns:
        int: A free port number

    Raises:
        IOError: If no free port is found in the range
        TypeError: If inputs are not integers
        ValueError: If start > end
    """
    # Input validation
    if not isinstance(start, int) or not isinstance(end, int):
        raise TypeError("Start and end must be integers")
    if start > end:
        raise ValueError("Start port must be less than or equal to end port")

    for port in range(start, end + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('', port))
                return port
        except OSError:
            continue
    raise IOError(f"Could not find a free port in the range {start}-{end}")


def log_function_call(func) -> callable:
    """
    A decorator that logs the function call and its arguments.

    Args:
        func: The function to be decorated

    Returns:
        function: The wrapped function with logging

    Raises:
        TypeError: If func is not callable
    """
    if not callable(func):
        raise TypeError("func must be callable")

    @wraps(func)
    def wrapper(*args, **kwargs):
        logging.info(f"Calling {func.__name__} with args: {args}, kwargs: {kwargs}")
        try:
            result = func(*args, **kwargs)
            logging.info(f"{func.__name__} returned: {result}")
            return result
        except Exception as e:
            logging.error(f"Exception in {func.__name__}: {e}")
            raise
    return wrapper


def generate_webconsole_keys_if_needed() -> List[Tuple[str, str]]:
    """
    Checks for WebConsole TLS key and certificate and generates them if not found.

    Returns:
        list: A list of tuples containing (level, message) for display
        Each tuple has:
        - level (str): 'info' or 'error'
        - message (str): The message to display

    Raises:
        Exception: For unexpected errors during key generation
    """
    messages = []
    config_dir = Path.home() / '.config' / 'vmanager'
    key_path = config_dir / 'key.pem'
    cert_path = config_dir / 'cert.pem'

    # Only proceed if required tools are available
    if not (check_virt_viewer() and check_websockify() and check_novnc_path()):
        messages.append(('info', "WebConsole tools not available. Skipping key generation."))
        return messages

    if not key_path.exists() or not cert_path.exists():
        messages.append(('info', "WebConsole TLS key/cert not found. Generating. .."))
        try:
            config_dir.mkdir(parents=True, exist_ok=True)
            command = [
                "openssl", "req", "-x509", "-newkey", "rsa:4096",
                "-keyout", str(key_path),
                "-out", str(cert_path),
                "-sha256", "-days", "365", "-nodes",
                "-subj", "/CN=localhost"
            ]
            try:
                result = subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                messages.append(('info', f"Successfully generated WebConsole TLS key and certificate in {config_dir}."))
            except subprocess.TimeoutExpired:
                error_message = "Failed to generate WebConsole TLS key/cert: Operation timed out"
                messages.append(('error', error_message))
            except subprocess.CalledProcessError as e:
                error_message = f"Failed to generate WebConsole TLS key/cert: {e.stderr.strip() if e.stderr else str(e)}"
                messages.append(('error', error_message))
            except FileNotFoundError:
                messages.append(('error', "openssl command not found. Please install openssl."))
        except Exception as e:
            error_message = f"Unexpected error generating WebConsole keys: {str(e)}"
            messages.append(('error', error_message))
    #else:
    #    messages.append(('info', "WebConsole TLS keys already exist."))

    return messages


def check_virt_viewer() -> bool:
    """
    Checks if virt-viewer is installed.

    Returns:
        bool: True if virt-viewer is installed, False otherwise

    Raises:
        Exception: For unexpected errors during check
    """
    try:
        return shutil.which("virt-viewer") is not None
    except Exception as e:
        logging.error(f"Error checking virt-viewer: {e}")
        return False


def check_firewalld() -> bool:
    """
    Checks if firewalld is installed.

    Returns:
        bool: True if firewalld is installed, False otherwise

    Raises:
        Exception: For unexpected errors during check
    """
    try:
        return shutil.which("firewalld") is not None
    except Exception as e:
        logging.error(f"Error checking firewalld: {e}")
        return False


def check_novnc_path() -> bool:
    """
    Check if novnc is available.

    Returns:
        bool: True if novnc path exists, False otherwise

    Raises:
        Exception: For unexpected errors during check
    """
    try:
        return os.path.exists("/usr/share/novnc")
    except Exception as e:
        logging.error(f"Error checking novnc path: {e}")
        return False


def check_websockify() -> bool:
    """
    Checks if websockify is installed.

    Returns:
        bool: True if websockify is installed, False otherwise

    Raises:
        Exception: For unexpected errors during check
    """
    try:
        return shutil.which("websockify") is not None
    except Exception as e:
        logging.error(f"Error checking websockify: {e}")
        return False


def check_is_firewalld_running() -> Union[str, bool]:
    """
    Check if firewalld is running.

    Returns:
        str or bool: 'active' if running, 'inactive' if stopped, False if not installed or error

    Raises:
        Exception: For unexpected errors during check
    """
    if not check_firewalld():
        return False

    try:
        result = subprocess.run(
            ["systemctl", "is-active", "firewalld"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return False
    except subprocess.CalledProcessError:
        return False
    except Exception as e:
        logging.error(f"Error checking firewalld status: {e}")
        return False


def extract_server_name_from_uri(server_name: str) -> str:
    """
    Extract server name from URI for display.

    Args:
        server_name (str): The connection URI

    Returns:
        str: Extracted server name for display

    Raises:
        TypeError: If server_name is not a string
    """
    # Input validation
    if not isinstance(server_name, str):
        raise TypeError("server_name must be a string")

    if not server_name:
        return "Unknown"

    if server_name.startswith('qemu+ssh://'):
        if '@' in server_name:
            server_display = server_name.split('@')[1].split(':')[0]
        else:
            server_display = server_name.split('://')[1].split(':')[0]
        if server_display.endswith('/system'):
            server_display = server_display[:-7]  # Remove "/system"
    elif server_name.startswith('qemu+tcp://') or server_name.startswith('qemu+tls://'):
        server_display = server_name.split('://')[1].split(':')[0]
    elif server_name == 'qemu:///system':
        server_display = 'Local'
    else:
        server_display = server_name.split('://')[1].split(':')[0] if '://' in server_name else server_name

    return server_display if server_display else "Unknown"
