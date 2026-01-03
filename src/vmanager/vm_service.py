"""
VM Service Layer
Handles all libvirt interactions and data processing.
"""
import time
import xml.etree.ElementTree as ET
import libvirt
from connection_manager import ConnectionManager
from constants import VmStatus

class VMService:
    """A service class to abstract libvirt operations."""

    def __init__(self):
        self.connection_manager = ConnectionManager()
        self._cpu_time_cache = {} # Cache for calculating CPU usage {uuid: (last_time, last_timestamp)}
        self._io_stats_cache = {} # Cache for calculating Disk/Net I/O {uuid: {'ts': ts, 'disk_read': bytes, ...}}
        self._domain_cache: dict[str, libvirt.virDomain] = {}
        self._uuid_to_conn_cache: dict[str, libvirt.virConnect] = {}
        self._cache_timestamp: float = 0.0
        self._cache_ttl: int = 5  # seconds

        self._vm_data_cache: dict[str, dict] = {}  # {uuid: {'info': (data), 'info_ts': ts, 'xml': 'data', 'xml_ts': ts}}
        self._info_cache_ttl: int = 5  # seconds
        self._xml_cache_ttl: int = 600  # 10 minutes

    def invalidate_domain_cache(self):
        """Invalidates the domain cache."""
        self._domain_cache.clear()
        self._uuid_to_conn_cache.clear()
        self._cache_timestamp = 0.0

    def invalidate_vm_cache(self, uuid: str):
        """Invalidates all cached data for a specific VM."""
        if uuid in self._vm_data_cache:
            del self._vm_data_cache[uuid]
        if uuid in self._cpu_time_cache:
            del self._cpu_time_cache[uuid]
        if uuid in self._io_stats_cache:
            del self._io_stats_cache[uuid]

    def _update_domain_cache(self, active_uris: list[str], force: bool = False):
        """Updates the domain and connection cache."""
        if not force and self._domain_cache and (time.time() - self._cache_timestamp < self._cache_ttl):
            return

        self.invalidate_domain_cache()
        if force:
            self._vm_data_cache.clear()
        active_connections = [self.connect(uri) for uri in active_uris if self.connect(uri)]
        for conn in active_connections:
            try:
                domains = conn.listAllDomains(0) or []
                for domain in domains:
                    uuid = domain.UUIDString()
                    self._domain_cache[uuid] = domain
                    self._uuid_to_conn_cache[uuid] = conn
            except libvirt.libvirtError:
                pass  # Or log error
        self._cache_timestamp = time.time()

    def _get_domain_info_and_xml(self, domain: libvirt.virDomain) -> tuple[tuple, str]:
        """Gets info and XML from cache or fetches them, fetching both if both are missing."""
        uuid = domain.UUIDString()
        now = time.time()

        # Ensure cache entry exists
        self._vm_data_cache.setdefault(uuid, {})
        vm_cache = self._vm_data_cache[uuid]

        info = vm_cache.get('info')
        info_ts = vm_cache.get('info_ts', 0)
        if info and now - info_ts >= self._info_cache_ttl:
            info = None

        xml = vm_cache.get('xml')
        xml_ts = vm_cache.get('xml_ts', 0)
        if xml and now - xml_ts >= self._xml_cache_ttl:
            xml = None

        if info is None and xml is None:
            info = domain.info()
            xml = domain.XMLDesc(0)
            vm_cache['info'] = info
            vm_cache['info_ts'] = now
            vm_cache['xml'] = xml
            vm_cache['xml_ts'] = now
        elif info is None:
            info = domain.info()
            vm_cache['info'] = info
            vm_cache['info_ts'] = now
        elif xml is None:
            xml = domain.XMLDesc(0)
            vm_cache['xml'] = xml
            vm_cache['xml_ts'] = now

        return info, xml

    def _get_domain_info(self, domain: libvirt.virDomain) -> tuple | None:
        """Gets domain info from cache or fetches it."""
        uuid = domain.UUIDString()
        now = time.time()

        self._vm_data_cache.setdefault(uuid, {})
        vm_cache = self._vm_data_cache[uuid]

        info = vm_cache.get('info')
        info_ts = vm_cache.get('info_ts', 0)

        if info is None or (now - info_ts >= self._info_cache_ttl):
            try:
                info = domain.info()
                vm_cache['info'] = info
                vm_cache['info_ts'] = now
            except libvirt.libvirtError:
                return None
        return info

    def _get_domain_xml(self, domain: libvirt.virDomain) -> str | None:
        """Gets domain XML from cache or fetches it."""
        uuid = domain.UUIDString()
        now = time.time()

        self._vm_data_cache.setdefault(uuid, {})
        vm_cache = self._vm_data_cache[uuid]

        xml = vm_cache.get('xml')
        xml_ts = vm_cache.get('xml_ts', 0)

        if xml is None or (now - xml_ts >= self._xml_cache_ttl):
            try:
                xml = domain.XMLDesc(0)
                vm_cache['xml'] = xml
                vm_cache['xml_ts'] = now
            except libvirt.libvirtError:
                return None
        return xml


    def get_vm_runtime_stats(self, domain: libvirt.virDomain) -> dict | None:
        """Gets live statistics for a given, active VM domain."""
        from vm_queries import get_status
        from datetime import datetime

        if not domain or not domain.isActive():
            return None

        uuid = domain.UUIDString()
        stats = {}
        try:
            # Status
            stats['status'] = get_status(domain)

            # CPU Usage
            cpu_stats = domain.getCPUStats(True)
            current_cpu_time = cpu_stats[0]['cpu_time']
            now = datetime.now().timestamp()

            cpu_percent = 0.0
            if uuid in self._cpu_time_cache:
                last_cpu_time, last_cpu_time_ts = self._cpu_time_cache[uuid]
                time_diff = now - last_cpu_time_ts
                cpu_diff = current_cpu_time - last_cpu_time
                if time_diff > 0:
                    info = self._get_domain_info(domain)
                    if not info: return None
                    num_cpus = info[3]
                    # nanoseconds to seconds, then divide by number of cpus
                    cpu_percent = (cpu_diff / (time_diff * 1_000_000_000)) * 100
                    cpu_percent = cpu_percent / num_cpus if num_cpus > 0 else 0

            stats['cpu_percent'] = cpu_percent
            self._cpu_time_cache[uuid] = (current_cpu_time, now)

            # Memory Usage
            mem_stats = domain.memoryStats()
            mem_percent = 0.0
            if 'rss' in mem_stats:
                info = self._get_domain_info(domain)
                if not info: return None
                total_mem_kb = info[1]
                if total_mem_kb > 0:
                    rss_kb = mem_stats['rss']
                    mem_percent = (rss_kb / total_mem_kb) * 100

            stats['mem_percent'] = mem_percent

            # Disk and Network I/O
            disk_read_bytes = 0
            disk_write_bytes = 0
            net_rx_bytes = 0
            net_tx_bytes = 0

            # Get XML to find devices
            xml_content = self._get_domain_xml(domain)

            # Use cached devices list if available and XML hasn't changed
            self._vm_data_cache.setdefault(uuid, {})
            vm_cache = self._vm_data_cache[uuid]

            # Check if we have a valid cached device list
            # We rely on xml_ts being updated when XML is refreshed
            current_xml_ts = vm_cache.get('xml_ts', 0)
            cached_devices_ts = vm_cache.get('devices_ts', 0)

            devices_list = vm_cache.get('devices_list')

            if devices_list is None or cached_devices_ts != current_xml_ts:
                # Parse XML and cache devices
                devices_list = {'disks': [], 'interfaces': []}
                if xml_content:
                    try:
                        root = ET.fromstring(xml_content)
                        # Disks
                        for disk in root.findall(".//devices/disk"):
                            target = disk.find("target")
                            if target is not None:
                                dev = target.get("dev")
                                if dev:
                                    devices_list['disks'].append(dev)
                        # Networks
                        for interface in root.findall(".//devices/interface"):
                            target = interface.find("target")
                            if target is not None:
                                dev = target.get("dev")
                                if dev:
                                    devices_list['interfaces'].append(dev)
                    except ET.ParseError:
                        pass

                vm_cache['devices_list'] = devices_list
                vm_cache['devices_ts'] = current_xml_ts

            # Use cached devices to query stats
            for dev in devices_list['disks']:
                try:
                    # blockStats returns (rd_req, rd_bytes, wr_req, wr_bytes, errs)
                    b_stats = domain.blockStats(dev)
                    disk_read_bytes += b_stats[1]
                    disk_write_bytes += b_stats[3]
                except libvirt.libvirtError:
                    pass

            for dev in devices_list['interfaces']:
                try:
                    # interfaceStats returns (rx_bytes, rx_packets, rx_errs, rx_drop, tx_bytes, tx_packets, tx_errs, tx_drop)
                    i_stats = domain.interfaceStats(dev)
                    net_rx_bytes += i_stats[0]
                    net_tx_bytes += i_stats[4]
                except libvirt.libvirtError:
                    pass

            # Calculate I/O Rates
            disk_read_rate = 0.0
            disk_write_rate = 0.0
            net_rx_rate = 0.0
            net_tx_rate = 0.0

            if uuid in self._io_stats_cache:
                last_stats = self._io_stats_cache[uuid]
                last_ts = last_stats['ts']
                time_diff = now - last_ts

                if time_diff > 0:
                    # Prevent negative rates if counters reset
                    d_read = disk_read_bytes - last_stats['disk_read']
                    d_write = disk_write_bytes - last_stats['disk_write']
                    n_rx = net_rx_bytes - last_stats['net_rx']
                    n_tx = net_tx_bytes - last_stats['net_tx']

                    disk_read_rate = d_read / time_diff if d_read >= 0 else 0
                    disk_write_rate = d_write / time_diff if d_write >= 0 else 0
                    net_rx_rate = n_rx / time_diff if n_rx >= 0 else 0
                    net_tx_rate = n_tx / time_diff if n_tx >= 0 else 0

            # Store cache
            self._io_stats_cache[uuid] = {
                'ts': now,
                'disk_read': disk_read_bytes,
                'disk_write': disk_write_bytes,
                'net_rx': net_rx_bytes,
                'net_tx': net_tx_bytes
            }

            stats['disk_read_kbps'] = disk_read_rate / 1024
            stats['disk_write_kbps'] = disk_write_rate / 1024
            stats['net_rx_kbps'] = net_rx_rate / 1024
            stats['net_tx_kbps'] = net_tx_rate / 1024

            return stats

        except libvirt.libvirtError as e:
            if e.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
                # If domain disappears, remove it from cache
                if uuid in self._cpu_time_cache:
                    del self._cpu_time_cache[uuid]
                if uuid in self._io_stats_cache:
                    del self._io_stats_cache[uuid]
            return None

    def connect(self, uri: str) -> libvirt.virConnect | None:
        """Connects to a libvirt URI."""
        return self.connection_manager.connect(uri)

    def disconnect(self, uri: str) -> None:
        """Disconnects from a libvirt URI."""
        self.connection_manager.disconnect(uri)

    def disconnect_all(self):
        """Disconnects all active libvirt connections."""
        self.connection_manager.disconnect_all()

    def perform_bulk_action(self, active_uris: list[str], vm_uuids: list[str], action_type: str, delete_storage_flag: bool, progress_callback: callable):
        """Performs a bulk action on a list of VMs, reporting progress via a callback."""
        from vm_actions import start_vm, stop_vm, force_off_vm, pause_vm, delete_vm
        from constants import VmAction

        action_dispatcher = {
            VmAction.START: start_vm,
            VmAction.STOP: stop_vm,
            VmAction.FORCE_OFF: force_off_vm,
            VmAction.PAUSE: pause_vm,
        }

        total_vms = len(vm_uuids)
        progress_callback("setup", total=total_vms)
        progress_callback("log", message=f"Starting bulk '{action_type}' on {total_vms} VMs...")

        successful_vms = []
        failed_vms = []

        found_domains = self.find_domains_by_uuids(active_uris, vm_uuids)

        for i, vm_uuid in enumerate(vm_uuids):
            domain = found_domains.get(vm_uuid)
            vm_name = domain.name() if domain else "Unknown VM"

            progress_callback("progress", name=vm_name, current=i + 1, total=total_vms)

            if not domain:
                msg = f"VM with UUID {vm_uuid} not found on any active server."
                progress_callback("log_error", message=msg)
                failed_vms.append(vm_uuid)
                continue

            try:
                action_func = action_dispatcher.get(action_type)
                if action_func:
                    action_func(domain)
                    msg = f"Performed '{action_type}' on VM '{vm_name}'."
                    progress_callback("log", message=msg)
                elif action_type == VmAction.DELETE:
                    # Special case for delete action's own callback
                    delete_log_callback = lambda m: progress_callback("log", message=m)
                    delete_vm(domain, delete_storage=delete_storage_flag, log_callback=delete_log_callback)
                else:
                    msg = f"Unknown bulk action type: {action_type}"
                    progress_callback("log_error", message=msg)
                    failed_vms.append(vm_name)
                    continue

                successful_vms.append(vm_name)

            except libvirt.libvirtError as e:
                msg = f"Error performing '{action_type}' on VM '{vm_name}': {e}"
                progress_callback("log_error", message=msg)
                failed_vms.append(vm_name)
            except Exception as e:
                msg = f"Unexpected error on '{action_type}' for VM '{vm_name}': {e}"
                progress_callback("log_error", message=msg)
                failed_vms.append(vm_name)

        return successful_vms, failed_vms

    def get_connection(self, uri: str) -> libvirt.virConnect | None:
        """Gets an existing connection object from the manager."""
        return self.connection_manager.get_connection(uri)

    def get_all_uris(self) -> list[str]:
        """Gets all URIs currently held by the connection manager."""
        return self.connection_manager.get_all_uris()

    def find_domains_by_uuids(self, active_uris: list[str], vm_uuids: list[str]) -> dict[str, libvirt.virDomain]:
        """Finds and returns a dictionary of domain objects from a list of UUIDs."""
        self._update_domain_cache(active_uris)

        found_domains = {}
        missing_uuids = []

        for uuid in vm_uuids:
            domain = self._domain_cache.get(uuid)
            if domain:
                try:
                    domain.info() # Check if domain is still valid
                    found_domains[uuid] = domain
                except libvirt.libvirtError:
                    missing_uuids.append(uuid)
            else:
                missing_uuids.append(uuid)

        if missing_uuids:
            self._update_domain_cache(active_uris, force=True)
            for uuid in missing_uuids:
                domain = self._domain_cache.get(uuid)
                if domain:
                    found_domains[uuid] = domain

        return found_domains

    def find_domain_by_uuid(self, active_uris: list[str], vm_uuid: str) -> libvirt.virDomain | None:
        """Finds and returns a domain object from a UUID across active connections."""
        domains = self.find_domains_by_uuids(active_uris, [vm_uuid])
        return domains.get(vm_uuid)

    def start_vm(self, domain: libvirt.virDomain) -> None:
        """Performs pre-flight checks and starts the VM."""
        from vm_actions import start_vm as start_action
        from storage_manager import check_domain_volumes_in_use

        if domain.isActive():
            return # Already running, do nothing

        # Perform pre-flight checks
        check_domain_volumes_in_use(domain)

        # If checks pass, start the VM
        start_action(domain)

    def stop_vm(self, domain: libvirt.virDomain) -> None:
        """Stops the VM."""
        from vm_actions import stop_vm as stop_action

        stop_action(domain)

    def pause_vm(self, domain: libvirt.virDomain) -> None:
        """Pauses the VM."""
        from vm_actions import pause_vm as pause_action

        pause_action(domain)

    def force_off_vm(self, domain: libvirt.virDomain) -> None:
        """Forcefully stops the VM."""
        from vm_actions import force_off_vm as force_off_action

        force_off_action(domain)

    def delete_vm(self, domain: libvirt.virDomain, delete_storage: bool) -> None:
        """Deletes the VM."""
        from vm_actions import delete_vm as delete_action

        uuid = domain.UUIDString()
        delete_action(domain, delete_storage=delete_storage)
        self.invalidate_vm_cache(uuid)


    def resume_vm(self, domain: libvirt.virDomain) -> None:
        """Resumes the VM."""
        domain.resume()

    def get_vm_details(self, active_uris: list[str], vm_uuid: str) -> tuple | None:
        """Finds a VM by UUID and returns its detailed information."""
        from vm_queries import (
            get_status, get_vm_description, get_vm_machine_info, get_vm_firmware_info,
            get_vm_networks_info, get_vm_network_ip, get_vm_network_dns_gateway_info,
            get_vm_disks_info, get_vm_devices_info, get_vm_shared_memory_info,
            get_boot_info, get_vm_video_model, get_vm_cpu_model
        )

        domain = self.find_domain_by_uuid(active_uris, vm_uuid)
        if not domain:
            return None

        conn_for_domain = self._uuid_to_conn_cache.get(vm_uuid)
        # Fallback to be safe, though this shouldn't be hit if cache is consistent
        if not conn_for_domain:
            for uri in active_uris:
                conn = self.connect(uri)
                if not conn:
                    continue
                try:
                    # Check if this connection owns the domain
                    if conn.lookupByUUIDString(vm_uuid).UUID() == domain.UUID():
                         conn_for_domain = conn
                         break
                except libvirt.libvirtError:
                    continue

        if not conn_for_domain:
            # This would indicate a cache inconsistency or a race condition
            return None

        try:
            info, xml_content = self._get_domain_info_and_xml(domain)
            if info is None or xml_content is None:
                # If we can't get essential info, we can't proceed.
                return None
            
            root = None
            try:
                root = ET.fromstring(xml_content)
            except ET.ParseError:
                pass

            vm_info = {
                'name': domain.name(),
                'uuid': domain.UUIDString(),
                'status': get_status(domain),
                'description': get_vm_description(domain),
                'cpu': info[3],
                'cpu_model': get_vm_cpu_model(root),
                'memory': info[2] // 1024,
                'machine_type': get_vm_machine_info(root),
                'firmware': get_vm_firmware_info(root),
                'shared_memory': get_vm_shared_memory_info(root),
                'networks': get_vm_networks_info(root),
                'detail_network': get_vm_network_ip(domain),
                'network_dns_gateway': get_vm_network_dns_gateway_info(domain, root=root),
                'disks': get_vm_disks_info(conn_for_domain, root),
                'devices': get_vm_devices_info(root),
                'boot': get_boot_info(conn_for_domain, root),
                'video_model': get_vm_video_model(root),
                'xml': xml_content,
            }
            return (vm_info, domain, conn_for_domain)
        except libvirt.libvirtError:
            # Propagate the error to be handled by the caller
            raise

    def get_vms(self, active_uris: list[str], servers: list[dict], sort_by: str, search_text: str, selected_vm_uuids: set[str], force: bool = False) -> tuple:
        """Fetch, filter, and return VM data without creating UI components."""
        self._update_domain_cache(active_uris, force=force)

        domains_with_conn = []
        for uuid, domain in self._domain_cache.items():
            conn = self._uuid_to_conn_cache.get(uuid)
            if conn:
                domains_with_conn.append((domain, conn))

        total_vms = len(domains_with_conn)
        server_names = []
        active_connections = [self.connect(uri) for uri in active_uris if self.connect(uri)]
        for conn in active_connections:
            try:
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
                pass

        total_vms_unfiltered = len(domains_with_conn)
        domains_to_display = domains_with_conn

        if sort_by != VmStatus.DEFAULT:
            if sort_by == VmStatus.SELECTED:
                domains_to_display = [(d, c) for d, c in domains_to_display if d.UUIDString() in selected_vm_uuids]
            else:
                def status_match(d):
                    info = self._get_domain_info(d)
                    if not info:
                        return False
                    status = info[0]
                    if sort_by == VmStatus.RUNNING:
                        return status == libvirt.VIR_DOMAIN_RUNNING
                    if sort_by == VmStatus.PAUSED:
                        return status == libvirt.VIR_DOMAIN_PAUSED
                    if sort_by == VmStatus.STOPPED:
                        return status not in [libvirt.VIR_DOMAIN_RUNNING, libvirt.VIR_DOMAIN_PAUSED]
                    return True

                domains_to_display = [(d, c) for d, c in domains_to_display if status_match(d)]

        if search_text:
            search_lower = search_text.lower()
            domains_to_display = [(d, c) for d, c in domains_to_display if search_lower in d.name().lower()]

        total_filtered_vms = len(domains_to_display)

        return domains_to_display, total_vms, total_filtered_vms, server_names
