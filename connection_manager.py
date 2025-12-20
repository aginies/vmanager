"""
Manages multiple libvirt connections.
"""
import libvirt
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError

class ConnectionManager:
    """A class to manage opening, closing, and storing multiple libvirt connections."""

    def __init__(self):
        """Initializes the ConnectionManager."""
        self.connections: dict[str, libvirt.virConnect] = {}  # uri -> virConnect object
        self.connection_errors: dict[str, str] = {}           # uri -> error message

    def connect(self, uri: str) -> libvirt.virConnect | None:
        """
        Connects to a given URI. If already connected, returns the existing connection.
        If the existing connection is dead, it will attempt to reconnect.
        """
        if uri in self.connections:
            conn = self.connections[uri]
            # Check if the connection is still alive and try to reconnect if not
            try:
                # Test the connection by calling a simple libvirt function
                conn.getLibVersion()
                return conn
            except libvirt.libvirtError:
                # Connection is dead, remove it and create a new one
                logging.warning(f"Connection to {uri} is dead, reconnecting...")
                self.disconnect(uri)
                return self._create_connection(uri)

        return self._create_connection(uri)

    def _create_connection(self, uri: str) -> libvirt.virConnect | None:
        """
        Creates a new connection to the given URI with a timeout.
        """
        try:
            logging.info(f"Opening new libvirt connection to {uri}")

            def open_connection():
                return libvirt.open(uri)

            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(open_connection)
                try:
                    # Wait for 10 seconds for the connection to establish
                    conn = future.result(timeout=10)
                except TimeoutError:
                    # If it times out, we raise a libvirtError to be caught by the existing error handling.
                    msg = "Connection timed out after 10 seconds."
                    # Check if the URI suggests an SSH connection
                    if 'ssh' in uri.lower(): # Use .lower() for robustness
                        msg += " If using SSH, this can happen if a password or SSH key passphrase is required."
                        msg += " Please use an SSH agent or a key without a passphrase, as interactive prompts are not supported."
                    raise libvirt.libvirtError(msg)

            if conn is None:
                # This case can happen if the URI is valid but the hypervisor is not running
                raise libvirt.libvirtError(f"libvirt.open('{uri}') returned None")
            
            self.connections[uri] = conn
            if uri in self.connection_errors:
                del self.connection_errors[uri]  # Clear previous error on successful connect
            return conn
        except libvirt.libvirtError as e:
            error_message = f"Failed to connect to '{uri}': {e}"
            logging.error(error_message)
            self.connection_errors[uri] = str(e)
            if uri in self.connections:
                del self.connections[uri]  # Clean up failed connection attempt
            return None

    def disconnect(self, uri: str) -> bool:
        """
        Closes and removes a specific connection from the manager.
        """
        if uri in self.connections:
            try:
                self.connections[uri].close()
                logging.info(f"Closed connection to {uri}")
            except libvirt.libvirtError as e:
                logging.error(f"Error closing connection to {uri}: {e}")
            finally:
                del self.connections[uri]
                return True
        return False

    def disconnect_all(self) -> None:
        """Closes all active connections managed by this instance."""
        logging.info("Closing all active libvirt connections.")
        for uri in list(self.connections.keys()):
            self.disconnect(uri)

    def get_connection(self, uri: str) -> libvirt.virConnect | None:
        """
        Retrieves an active connection object for a given URI.
        """
        return self.connections.get(uri)

    def get_all_connections(self) -> list[libvirt.virConnect]:
        """
        Returns a list of all active libvirt connection objects.
        """
        return list(self.connections.values())

    def get_all_uris(self) -> list[str]:
        """
        Returns a list of all URIs with active connections.
        """
        return list(self.connections.keys())

    def get_connection_error(self, uri: str) -> str | None:
        """
        Returns the last error message for a given URI, or None if no error.
        """
        return self.connection_errors.get(uri)

    def has_connection(self, uri: str) -> bool:
        """
        Checks if a connection to the given URI exists.
        """
        return uri in self.connections

    def is_connection_alive(self, uri: str) -> bool:
        """
        Checks if a connection to the given URI is alive.
        """
        if uri not in self.connections:
            return False
        
        try:
            # Test the connection by calling a simple libvirt function
            self.connections[uri].getLibVersion()
            return True
        except libvirt.libvirtError:
            return False
