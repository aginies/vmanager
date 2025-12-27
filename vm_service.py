"""
VM Service Layer
Handles all libvirt interactions and data processing.
"""
import libvirt
from connection_manager import ConnectionManager

class VMService:
    """A service class to abstract libvirt operations."""

    def __init__(self):
        self.connection_manager = ConnectionManager()

    def connect(self, uri: str) -> libvirt.virConnect | None:
        """Connects to a libvirt URI."""
        return self.connection_manager.connect(uri)

    def disconnect(self, uri: str) -> None:
        """Disconnects from a libvirt URI."""
        self.connection_manager.disconnect(uri)

    def disconnect_all(self):
        """Disconnects all active libvirt connections."""
        self.connection_manager.disconnect_all()

    def get_vms(self, active_uris: list[str], servers: list[dict], sort_by: str, search_text: str, selected_vm_uuids: list[str]) -> tuple:
        """Fetch, filter, and return VM data without creating UI components."""
        domains_with_conn = []
        total_vms = 0
        server_names = []

        active_connections = [self.connect(uri) for uri in active_uris if self.connect(uri)]

        for conn in active_connections:
            try:
                domains = conn.listAllDomains(0) or []
                total_vms += len(domains)
                for domain in domains:
                    domains_with_conn.append((domain, conn))

                uri = conn.getURI()
                found = False
                for server in servers:
                    if server['uri'] == uri:
                        server_names.append(server['name'])
                        found = True
                        break
                if not found:
                    server_names.append(uri)
            except libvirt.libvirtError:
                # In a more advanced implementation, this could return an error message
                # for the UI to display.
                pass

        total_vms_unfiltered = len(domains_with_conn)
        domains_to_display = domains_with_conn

        if sort_by != "default":
            if sort_by == "running":
                domains_to_display = [(d, c) for d, c in domains_to_display if d.info()[0] == libvirt.VIR_DOMAIN_RUNNING]
            elif sort_by == "paused":
                domains_to_display = [(d, c) for d, c in domains_to_display if d.info()[0] == libvirt.VIR_DOMAIN_PAUSED]
            elif sort_by == "stopped":
                domains_to_display = [(d, c) for d, c in domains_to_display if d.info()[0] not in [libvirt.VIR_DOMAIN_RUNNING, libvirt.VIR_DOMAIN_PAUSED]]
            elif sort_by == "selected":
                domains_to_display = [(d, c) for d, c in domains_to_display if d.UUIDString() in selected_vm_uuids]

        if search_text:
            domains_to_display = [(d, c) for d, c in domains_to_display if search_text.lower() in d.name().lower()]

        total_filtered_vms = len(domains_to_display)
        
        return domains_to_display, total_vms, total_filtered_vms, server_names
