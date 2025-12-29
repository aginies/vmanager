"""
Main Webconsole management functions
"""
import logging
import os
import subprocess
import tempfile
from datetime import datetime
from functools import partial
from pathlib import Path
from urllib.parse import urlparse

import libvirt

from config import load_config, get_log_path
from utils import find_free_port
from vm_queries import get_vm_graphics_info
from vmcard_dialog import WebConsoleDialog


class WebConsoleManager:
    """Manages websockify processes and SSH tunnels for web console access."""

    def __init__(self, app):
        self.app = app
        self.config = load_config()
        self.processes = {}  # Replaces app.websockify_processes

    @staticmethod
    def is_remote_connection(uri: str) -> bool:
        """Determines if the connection URI is for a remote qemu+ssh host."""
        if not uri:
            return False
        parsed_uri = urlparse(uri)
        return (
            parsed_uri.hostname not in (None, "localhost", "127.0.0.1")
            and parsed_uri.scheme == "qemu+ssh"
        )


    def is_running(self, uuid: str) -> bool:
        """Check if a web console process is running for a given VM UUID."""
        if uuid in self.processes:
            proc, _, _, _, _ = self.processes[uuid]
            if proc.poll() is None:
                return True
            else:
                # Process has terminated, clean it up to prevent stale entries
                del self.processes[uuid]
                return False
        return False

    def start_console(self, vm, conn):
        """Starts a web console for a given VM."""
        self.config = load_config()  # Reload config to get latest settings
        logging.info(f"Web console requested for VM: {vm.name()}")
        uuid = vm.UUIDString()
        vm_name = vm.name()

        if self.is_running(uuid):
            _, _, url, _, _ = self.processes[uuid]

            stopper_worker = partial(self.stop_console, uuid, vm_name)
            def on_dialog_dismiss(result):
                if result == "stop":
                    self.app.worker_manager.run(
                        stopper_worker, name=f"stop_console_{uuid}"
                    )
            self.app.call_from_thread(self.app.push_screen, WebConsoleDialog(url), on_dialog_dismiss)
            return

        try:
            xml_content = vm.XMLDesc(0)
            graphics_info = get_vm_graphics_info(xml_content)

            if graphics_info.get('type') != 'vnc':
                self.app.call_from_thread(self.app.show_error_message, "Web console only supports VNC graphics.")
                return

            vnc_port = graphics_info.get('port')
            if not vnc_port or vnc_port == '-1':
                self.app.call_from_thread(self.app.show_error_message, "Could not determine VNC port for the VM.")
                return

            is_remote_ssh = WebConsoleManager.is_remote_connection(conn.getURI())

            if is_remote_ssh and self.config.get('REMOTE_WEBCONSOLE', False):
                self._launch_remote_websockify(uuid, vm_name, conn, int(vnc_port), graphics_info)
            else:
                vnc_target_host, vnc_target_port, ssh_info = self._setup_ssh_tunnel(
                    uuid, conn, vm_name, int(vnc_port), graphics_info
                )
                if vnc_target_host and vnc_target_port:
                    self._launch_websockify(uuid, vm_name, vnc_target_host, vnc_target_port, ssh_info)

        except (libvirt.libvirtError, FileNotFoundError, Exception) as e:
            self.app.call_from_thread(self.app.show_error_message, f"Failed to start web console: {e}")
            logging.error(f"Error during web console startup for VM {vm_name}: {e}", exc_info=True)

    def stop_console(self, uuid: str, vm_name: str):
        """Stops the websockify process and any associated SSH tunnel."""
        if uuid not in self.processes:
            return

        websockify_proc, _, _, ssh_info, _ = self.processes[uuid]
        websockify_proc.terminate()

        if ssh_info:
            self._stop_ssh_tunnel(vm_name, ssh_info)

        if uuid in self.processes:
            del self.processes[uuid]
        self.app.call_from_thread(self.app.show_success_message, "Web console stopped.")

    def terminate_all(self):
        """Terminates all running websockify and SSH tunnel processes."""
        for uuid, process_data in list(self.processes.items()):
            vm_name = process_data[4]
            self.stop_console(uuid, vm_name)

    def _monitor_and_kill_service(self, uuid: str, vm_name: str, proc: subprocess.Popen):
        """Monitors a process's stderr for a connection and then stops it."""
        if not proc.stderr:
            return

        try:
            for line in iter(proc.stderr.readline, ''):
                line = line.strip()
                logging.debug(f"websockify[{vm_name}]: {line}")

                if "INFO: connection from" in line:
                    logging.info(f"Web console client connected for {vm_name}. Scheduling service stop in 2 seconds.")

                    stopper_worker = partial(self.stop_console, uuid, vm_name)
                    self.app.call_later(
                        2,
                        lambda: self.app.worker_manager.run(
                            stopper_worker, name=f"stop_console_{uuid}"
                        ),
                    )
                    break
        except Exception as e:
            logging.error(f"Error monitoring websockify for {vm_name}: {e}")
        finally:
            if proc.stderr:
                proc.stderr.close()

    def _launch_remote_websockify(self, uuid: str, vm_name: str, conn, vnc_port: int, graphics_info: dict):
        """Launches websockify on the remote server via SSH and shows the console dialog."""
        logging.info(f"Launching remote websockify for VM: {vm_name}")

        # Parse SSH connection details
        parsed_uri = urlparse(conn.getURI())
        user = parsed_uri.username
        host = parsed_uri.hostname
        remote_user_host = f"{user}@{host}" if user else host

        # Determine target VNC host on the remote server
        vnc_target_host = graphics_info.get('listen', '127.0.0.1')
        if vnc_target_host in ['0.0.0.0', '::']:
            vnc_target_host = '127.0.0.1'

        # Find a free port for websockify on the remote server.
        web_port = find_free_port(int(self.app.WC_PORT_RANGE_START), int(self.app.WC_PORT_RANGE_END))
        if not web_port:
            self.app.call_from_thread(self.app.show_error_message, "Could not find a free port for the web console.")
            return

        remote_websockify_path = self.config.get('websockify_path', '/usr/bin/websockify')
        remote_novnc_path = self.config.get("novnc_path", "/usr/share/novnc/")

        # Construct the websockify command to run on the remote server
        remote_websockify_cmd_list = [
            remote_websockify_path, "--run-once", "--verbose", str(web_port),
            f"{vnc_target_host}:{vnc_port}", "--web", remote_novnc_path
        ]

        # Assume remote config directory for certs
        remote_config_dir = "~/.config/vmanager"
        remote_cert_file = f"{remote_config_dir}/cert.pem"
        remote_key_file = f"{remote_config_dir}/key.pem"
        url_scheme = "http"

        # Check for remote certs and keys by attempting to add them to the command
        remote_config_check_cmd = (
            f"if [ -f {remote_cert_file} ] && [ -f {remote_key_file} ]; then "
            f"echo 'cert_exists'; else echo 'no_cert'; fi"
        )

        try:
            check_result = subprocess.run(
                ["ssh", remote_user_host, remote_config_check_cmd], 
                capture_output=True, text=True, check=True, timeout=5
            )
            if "cert_exists" in check_result.stdout:
                remote_websockify_cmd_list.extend(["--cert", remote_cert_file, "--key", remote_key_file])
                url_scheme = "https"
                self.app.call_from_thread(self.app.show_success_message, "Remote cert/key found, using secure wss connection.")
            else:
                self.app.call_from_thread(self.app.show_success_message, "No remote cert/key found, using insecure ws connection.")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
            logging.warning(f"Could not check for remote certs: {e}. Proceeding without SSL options.")
            self.app.call_from_thread(self.app.show_success_message, "Could not check for remote cert/key, using insecure ws connection.")

        remote_websockify_cmd_str = " ".join(remote_websockify_cmd_list)

        ssh_command_list = [
            "ssh", remote_user_host,
            remote_websockify_cmd_str
        ]

        logging.info(f"Executing remote websockify command: {' '.join(ssh_command_list)}")

        proc = subprocess.Popen(ssh_command_list, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding='utf-8')

        monitor_callable = partial(
            self._monitor_and_kill_service, uuid, vm_name, proc
        )
        self.app.worker_manager.run(
            monitor_callable,
            name=f"monitor_{vm_name}",
            group="webconsole_monitors",
        )

        quality = self.config.get('VNC_QUALITY', 0)
        compression = self.config.get('VNC_COMPRESSION', 9)
        url = f"{url_scheme}://{host}:{web_port}/vnc.html?path=websockify&quality={quality}&compression={compression}"

        self.processes[uuid] = (proc, web_port, url, {}, vm_name)

        stopper_worker = partial(self.stop_console, uuid, vm_name)
        def on_dialog_dismiss(result):
            if result == "stop":
                self.app.worker_manager.run(
                    stopper_worker, name=f"stop_console_{uuid}"
                )

        self.app.call_from_thread(
            self.app.push_screen,
            WebConsoleDialog(url),
            on_dialog_dismiss
        )

    def _setup_ssh_tunnel(self, uuid: str, conn, vm_name: str, vnc_port: int, graphics_info: dict) -> tuple[str | None, int | None, dict]:
        """Sets up an SSH tunnel for remote connections if needed."""
        is_remote_ssh = WebConsoleManager.is_remote_connection(conn.getURI())

        vnc_target_host = graphics_info.get('listen', '127.0.0.1')
        if vnc_target_host in ['0.0.0.0', '::']:
            vnc_target_host = '127.0.0.1'

        if not is_remote_ssh:
            return vnc_target_host, vnc_port, {}

        self.app.call_from_thread(self.app.show_success_message, "Remote connection detected. Setting up SSH tunnel...")
        user = parsed_uri.username
        host = parsed_uri.hostname
        remote_user_host = f"{user}@{host}" if user else host

        temp_dir = tempfile.gettempdir()
        socket_name = f"vmanager_ssh_{uuid}_{datetime.now().strftime('%Y%m%d%H%M%S')}.sock"
        control_socket = os.path.join(temp_dir, socket_name)

        tunnel_port = find_free_port(int(self.app.WC_PORT_RANGE_START), int(self.app.WC_PORT_RANGE_END))
        if not tunnel_port:
            self.app.call_from_thread(self.app.show_error_message, "Could not find a free port for the SSH tunnel.")
            return None, None, {}


        ssh_cmd = [
            "ssh", "-M", "-S", control_socket, "-f", "-N",
            "-L", f"{tunnel_port}:{vnc_target_host}:{vnc_port}", remote_user_host
        ]

        try:
            subprocess.run(ssh_cmd, check=True, timeout=10)
            logging.info(f"SSH tunnel created for VM {vm_name} via {control_socket}")
            return '127.0.0.1', tunnel_port, {"control_socket": control_socket}
        except FileNotFoundError:
            self.app.call_from_thread(self.app.show_error_message, "SSH command not found. Cannot create tunnel.")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            self.app.call_from_thread(self.app.show_error_message, f"Failed to create SSH tunnel: {e}")
            logging.error(f"SSH tunnel command failed: {' '.join(ssh_cmd)}")

        return None, None, {}


    def _launch_websockify(self, uuid: str, vm_name: str, host: str, port: int, ssh_info: dict):
        """Launches the websockify process and shows the console dialog."""
        web_port = find_free_port(int(self.app.WC_PORT_RANGE_START), int(self.app.WC_PORT_RANGE_END))
        if not web_port:
            self.app.call_from_thread(self.app.show_error_message, "Could not find a free port for the web console.")
            return

        websockify_path = self.config.get('websockify_path', '/usr/bin/websockify')
        novnc_path = self.config.get("novnc_path", "/usr/share/novnc/")

        websockify_cmd = [
            websockify_path, "--run-once", str(web_port),
            f"{host}:{port}", "--web", novnc_path
        ]

        config_dir = Path.home() / '.config' / 'vmanager'
        cert_file = config_dir / 'cert.pem'
        key_file = config_dir / 'key.pem'
        url_scheme = "http"

        log_file_path = get_log_path()
        with open(log_file_path, 'a') as log_file_handle:
            if cert_file.exists() and key_file.exists():
                websockify_cmd.extend(["--cert", str(cert_file), "--key", str(key_file)])
                url_scheme = "https"
                self.app.call_from_thread(self.app.show_success_message, "Found cert/key, using secure wss connection.")

            proc = subprocess.Popen(websockify_cmd, stdout=subprocess.DEVNULL, stderr=log_file_handle)

            url = f"{url_scheme}://localhost:{web_port}/vnc.html?path=websockify"
            self.processes[uuid] = (proc, web_port, url, ssh_info, vm_name)

            stopper_worker = partial(self.stop_console, uuid, vm_name)
            def on_dialog_dismiss(result):
                if result == "stop":
                    self.app.worker_manager.run(
                        stopper_worker, name=f"stop_console_{uuid}"
                    )

            self.app.call_from_thread(
                self.app.push_screen,
                WebConsoleDialog(url),
                on_dialog_dismiss
            )

    def _stop_ssh_tunnel(self, vm_name: str, ssh_info: dict):
        """Stops the SSH tunnel using its control socket."""
        control_socket = ssh_info.get("control_socket")
        if not control_socket:
            return
        try:
            stop_cmd = ["ssh", "-S", control_socket, "-O", "exit", "dummy-host"]
            subprocess.run(stop_cmd, check=True, timeout=5, capture_output=True)
            logging.info(f"SSH tunnel stopped for VM {vm_name} using socket {control_socket}")
        except FileNotFoundError:
            self.app.call_from_thread(self.app.show_error_message, "'ssh' command not found.")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logging.warning(f"Could not stop SSH tunnel cleanly for VM {vm_name}: {e.stderr.decode() if e.stderr else e}")
        finally:
            if os.path.exists(control_socket):
                os.remove(control_socket)
