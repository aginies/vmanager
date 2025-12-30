"""
Module for retrieving information about virtual machines.
"""
import xml.etree.ElementTree as ET
import logging
import libvirt
from libvirt_utils import _get_disabled_disks_elem, VIRTUI_MANAGER_NS
from vm_cache import get_from_cache, set_in_cache
#from utils import log_function_call



def get_vm_info(conn):
    """
    get all VM info
    """
    if conn is None:
        return []

    vm_info_list = []
    domains = conn.listAllDomains(0)
    if domains is not None:
        for domain in domains:
            uuid = domain.UUIDString()
            cached_info = get_from_cache(uuid)
            if cached_info:
                # To ensure the status is fresh, we can re-fetch just the status
                cached_info['status'] = get_status(domain)
                vm_info_list.append(cached_info)
                continue

            info = domain.info()
            xml_content = domain.XMLDesc(0)
            vm_info = {
                'name': domain.name(),
                'uuid': domain.UUIDString(),
                'status': get_status(domain),
                'description': get_vm_description(domain),
                'cpu': info[3],
                'memory': info[2] // 1024,  # Convert KiB to MiB
                'machine_type': get_vm_machine_info(xml_content),
                'firmware': get_vm_firmware_info(xml_content),
                'networks': get_vm_networks_info(xml_content),
                'graphics': get_vm_graphics_info(xml_content),
                'rng': get_vm_rng_info(xml_content),
                'watchdog': get_vm_watchdog_info(xml_content),
                'tmp': get_vm_tpm_info(xml_content),
                'input': get_vm_input_info(xml_content),
                'boot': get_boot_info(xml_content, conn),
                'detail_network': get_vm_network_ip(domain),
                'network_dns_gateway': get_vm_network_dns_gateway_info(domain),
                'disks': get_vm_disks_info(conn, xml_content),
                'devices': get_vm_devices_info(xml_content),
            }
            set_in_cache(uuid, vm_info)
            vm_info_list.append(vm_info)

    return vm_info_list

#@log_function_call
def get_vm_network_dns_gateway_info(domain: libvirt.virDomain):
    """
    Extracts DNS and gateway information for networks connected to the VM.
    """
    if not domain:
        return []

    conn = domain.connect()
    xml_content = domain.XMLDesc(0)
    root = ET.fromstring(xml_content)

    network_details = []

    # Find all network names from the VM's interfaces
    vm_networks = []
    for interface in root.findall(".//devices/interface"):
        source = interface.find("source")
        if source is not None:
            network_name = source.get("network")
            if network_name and network_name not in vm_networks:
                vm_networks.append(network_name)

    for net_name in vm_networks:
        try:
            network = conn.networkLookupByName(net_name)
            net_xml = network.XMLDesc(0)
            net_root = ET.fromstring(net_xml)

            gateway = None
            ip_elem = net_root.find("ip")
            if ip_elem is not None:
                gateway = ip_elem.get("address")

            dns_servers = []
            dns_elem = net_root.find("dns")
            if dns_elem is not None:
                for server in dns_elem.findall("server"):
                    dns_servers.append(server.get("address"))

            if gateway or dns_servers:
                network_details.append({
                    "network_name": net_name,
                    "gateway": gateway,
                    "dns_servers": dns_servers
                })

        except libvirt.libvirtError:
            # Network might not be found or other libvirt error
            continue

    return network_details

def get_status(domain):
    """
    state of a VM
    """
    state = domain.info()[0]
    if state == libvirt.VIR_DOMAIN_RUNNING:
        return 'Running'
    elif state == libvirt.VIR_DOMAIN_PAUSED:
        return 'Paused'
    else:
        return 'Stopped'

def get_vm_description(domain):
    """
    desc of the VM
    """
    try:
        return domain.metadata(libvirt.VIR_DOMAIN_METADATA_DESCRIPTION, None)
    except libvirt.libvirtError:
        return "No description available"

def get_vm_firmware_info(xml_content: str) -> dict:
    """
    Extracts firmware (BIOS/UEFI) from a VM's XML definition.
    Returns a dictionary with firmware info.
    """
    firmware_info = {'type': 'BIOS', 'path': None, 'secure_boot': False} # Default to BIOS

    try:
        root = ET.fromstring(xml_content)
        os_elem = root.find('os')

        if os_elem is not None:
            loader_elem = os_elem.find('loader')
            if loader_elem is not None and loader_elem.get('type') == 'pflash':
                loader_path = loader_elem.text
                if loader_path:
                    firmware_info['type'] = 'UEFI'
                    firmware_info['path'] = loader_path
                    if loader_elem.get('secure') == 'yes':
                        firmware_info['secure_boot'] = True
            else:
                bootloader_elem = os_elem.find('bootloader')
                if bootloader_elem is not None:
                     firmware_info['type'] = 'BIOS'

    except ET.ParseError:
        pass # Return default values if XML parsing fails

    return firmware_info

def get_vm_machine_info(xml_content: str) -> str:
    """
    Extracts machine type from a VM's XML definition.
    """
    machine_type = "N/A"

    try:
        root = ET.fromstring(xml_content)
        os_elem = root.find('os')

        # Get machine type from the 'machine' attribute of the 'type' element within 'os'
        if os_elem is not None:
            type_elem = os_elem.find('type')
            if type_elem is not None and 'machine' in type_elem.attrib:
                machine_type = type_elem.get('machine')

    except ET.ParseError:
        pass # Return default values if XML parsing fails

    return machine_type

def get_vm_networks_info(xml_content: str) -> list[dict]:
    """Extracts network interface information from a VM's XML definition."""
    root = ET.fromstring(xml_content)
    networks = []
    for interface in root.findall(".//devices/interface"):
        mac_address_node = interface.find("mac")
        if mac_address_node is None:
            continue
        mac_address = mac_address_node.get("address")

        source = interface.find("source")
        network_name = None
        if source is not None:
            network_name = source.get("network")

        model_node = interface.find("model")
        model = model_node.get("type") if model_node is not None else "default"

        # We are interested in interfaces that are part of a network
        if network_name:
            networks.append({"mac": mac_address, "network": network_name, "model": model})
    return networks


def get_vm_network_ip(domain) -> list:
    """
    Retrieves network interface IP addresses for a given VM domain.
    Requires qemu-guest-agent to be installed and running in the guest VM.
    Returns a list of dictionaries, where each dictionary represents an interface
    and contains its MAC address and a list of IP addresses.
    """
    if domain.state()[0] == libvirt.VIR_DOMAIN_RUNNING or domain.state()[0] == libvirt.VIR_DOMAIN_PAUSED:
        ip_addresses = []
        try:
            addresses = domain.interfaceAddresses(libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE)
            if addresses:
                for iface_name, iface_info in addresses.items():
                    interface_ips = {
                        'interface': iface_name,
                        'mac': iface_info['hwaddr'],
                        'ipv4': [],
                        'ipv6': []
                    }
                    if iface_info['addrs']:
                        for addr in iface_info['addrs']:
                            if addr['type'] == libvirt.VIR_IP_ADDR_TYPE_IPV4:
                                interface_ips['ipv4'].append(f"{addr['addr']}/{addr['prefix']}")
                            elif addr['type'] == libvirt.VIR_IP_ADDR_TYPE_IPV6:
                                interface_ips['ipv6'].append(f"{addr['addr']}/{addr['prefix']}")
                    ip_addresses.append(interface_ips)
        except libvirt.libvirtError:
            pass # Return empty list if there's an error or VM is not running
        return ip_addresses
    return []

def get_vm_devices_info(xml_content: str) -> dict:
    """
    Extracts information about various virtual devices from a VM's XML definition.
    """
    devices_info = {
        'virtiofs': [],
        'virtio-serial': [],
        'isa-serial': [],
        'qemu_guest_agent': [],
        'graphics': [],
        'usb': [],
        'random': [],
        'tpm': [],
        'video': [],
        'watchdog': [],
        'input': [],
        'sound': [],
        'scsi': [],
    }

    try:
        root = ET.fromstring(xml_content)
        devices = root.find("devices")

        if devices is not None:
            # virtiofs
            for fs_elem in devices.findall("./filesystem[@type='mount']"):
                driver = fs_elem.find('driver')
                if driver is not None and driver.get('type') == 'virtiofs':
                    source = fs_elem.find('source')
                    target = fs_elem.find('target')
                    if source is not None and target is not None:
                        readonly = fs_elem.find('readonly') is not None
                        devices_info['virtiofs'].append({
                            'source': source.get('dir'),
                            'target': target.get('dir'),
                            'readonly': readonly
                        })

            # virtio-serial and qemu.guest_agent
            for channel_elem in devices.findall('channel'):
                channel_type = channel_elem.get('type')
                if channel_type == 'virtio':
                    target_elem = channel_elem.find('target')
                    if target_elem is not None:
                        name = target_elem.get('name')
                        if name == 'org.qemu.guest_agent.0':
                            devices_info['qemu_guest_agent'].append({'type': 'virtio-serial', 'name': name})
                        else:
                            devices_info['virtio-serial'].append({'name': name})
                elif channel_type == 'unix':
                    target_elem = channel_elem.find('target')
                    if target_elem is not None and target_elem.get('name') == 'org.qemu.guest_agent.0':
                        devices_info['qemu_guest_agent'].append({'type': 'unix-channel', 'path': target_elem.get('path')})

            # isa-serial
            for serial_elem in devices.findall("./serial[@type='isa']"):
                target_elem = serial_elem.find('target')
                if target_elem is not None:
                    port = target_elem.get('port', '0')
                    devices_info['isa-serial'].append({'port': port})

            # graphics (spice, vnc, etc.)
            for graphics_elem in devices.findall('graphics'):
                graphics_type = graphics_elem.get('type')
                if graphics_type:
                    detail = {'type': graphics_type}
                    if graphics_type == 'spice':
                        detail.update({
                            'port': graphics_elem.get('port'),
                            'tlsPort': graphics_elem.get('tlsPort'),
                            'autoport': graphics_elem.get('autoport'),
                        })
                    elif graphics_type == 'vnc':
                        detail.update({
                            'port': graphics_elem.get('port'),
                            'autoport': graphics_elem.get('autoport'),
                            'display': graphics_elem.get('display'),
                        })
                    devices_info['graphics'].append(detail)


            # usb controllers and devices
            for controller_elem in devices.findall("./controller[@type='usb']"):
                devices_info['usb'].append({
                    'type': 'controller',
                    'model': controller_elem.get('model'),
                    'index': controller_elem.get('index')
                })
            for usb_dev_elem in devices.findall("./hostdev[@type='usb']"):
                address = usb_dev_elem.find('address')
                if address is not None:
                    bus = address.get('bus')
                    device = address.get('device')
                    devices_info['usb'].append({'type': 'hostdev', 'bus': bus, 'device': device})

            # scsi controllers
            for controller_elem in devices.findall("./controller[@type='scsi']"):
                devices_info['scsi'].append({
                    'type': 'controller',
                    'model': controller_elem.get('model'),
                    'index': controller_elem.get('index')
                })

            # video
            for video_elem in devices.findall('video'):
                model_elem = video_elem.find('model')
                if model_elem is not None:
                    devices_info['video'].append({
                        'type': model_elem.get('type'),
                        'vram': model_elem.get('vram'),
                        'heads': model_elem.get('heads'),
                    })
            # watchdog
            for watchdog_elem in devices.findall('watchdog'):
                devices_info['watchdog'].append({
                    'model': watchdog_elem.get('model'),
                    'action': watchdog_elem.get('action'),
                })
            # input
            for input_elem in devices.findall('input'):
                devices_info['input'].append({
                    'type': input_elem.get('type'),
                    'bus': input_elem.get('bus'),
                })
            # sound
            for sound_elem in devices.findall('sound'):
                model_elem = sound_elem.find('model')
                if model_elem is not None:
                    devices_info['sound'].append({
                        'model': model_elem.get('model'),
                })
            # random number generator
            rng_elem = devices.find("./rng")
            if rng_elem is not None:
                devices_info['random'].append({'model': rng_elem.get('model')})

            # tpm
            tpm_elem = devices.find("./tpm")
            if tpm_elem is not None:
                model = tpm_elem.get('model')
                devices_info['tpm'].append({'model': model})


    except ET.ParseError:
        pass

    return devices_info


def get_vm_disks_info(conn: libvirt.virConnect, xml_content: str) -> list[dict]:
    """
    Extracts disks info from a VM's XML definition.
    Returns a list of dictionaries with 'path', 'status', 'bus', 'cache_mode', and 'discard_mode'.
    """
    disks = []
    try:
        root = ET.fromstring(xml_content)
        # Enabled disks
        devices = root.find("devices")
        if devices is not None:
            for disk in devices.findall("disk"):
                disk_path = ""
                disk_source = disk.find("source")
                if disk_source is not None:
                    if "file" in disk_source.attrib:
                        disk_path = disk_source.attrib["file"]
                    elif "dev" in disk_source.attrib:
                        disk_path = disk_source.attrib["dev"]
                    elif "pool" in disk_source.attrib and "volume" in disk_source.attrib:
                        pool_name = disk_source.attrib["pool"]
                        vol_name = disk_source.attrib["volume"]
                        try:
                            pool = conn.storagePoolLookupByName(pool_name)
                            vol = pool.storageVolLookupByName(vol_name)
                            disk_path = vol.path()
                        except libvirt.libvirtError:
                            disk_path = f"Error: volume '{vol_name}' not found in pool '{pool_name}'"

                if disk_path:
                    driver = disk.find("driver")
                    cache_mode = driver.get("cache") if driver is not None else "default"
                    discard_mode = driver.get("discard") if driver is not None else "ignore"
                    
                    target_elem = disk.find('target')
                    bus = target_elem.get('bus') if target_elem is not None else 'N/A'

                    disks.append({'path': disk_path, 'status': 'enabled', 'cache_mode': cache_mode, 'discard_mode': discard_mode, 'bus': bus})

        # Disabled disks from metadata
        metadata_elem = root.find('metadata')
        if metadata_elem is not None:
            vmanager_meta_elem = metadata_elem.find(f'{{{VIRTUI_MANAGER_NS}}}virtuimanager')
            if vmanager_meta_elem is not None:
                # Use _get_disabled_disks_elem to get the element correctly
                disabled_disks_elem = _get_disabled_disks_elem(root)
                if disabled_disks_elem is not None:
                    for disk in disabled_disks_elem.findall('disk'):
                        disk_path = ""
                        disk_source = disk.find("source")
                        if disk_source is not None:
                            if "file" in disk_source.attrib:
                                disk_path = disk_source.attrib["file"]
                            elif "dev" in disk_source.attrib:
                                disk_path = disk_source.attrib["dev"]
                            elif "pool" in disk_source.attrib and "volume" in disk_source.attrib:
                                pool_name = disk_source.attrib["pool"]
                                vol_name = disk_source.attrib["volume"]
                                try:
                                    pool = conn.storagePoolLookupByName(pool_name)
                                    vol = pool.storageVolLookupByName(vol_name)
                                    disk_path = vol.path()
                                except libvirt.libvirtError:
                                    disk_path = f"Error: volume '{vol_name}' not found in pool '{pool_name}'"

                        if disk_path:
                            driver = disk.find("driver")
                            cache_mode = driver.get("cache") if driver is not None else "default"
                            discard_mode = driver.get("discard") if driver is not None else "ignore"
                            
                            target_elem = disk.find('target')
                            bus = target_elem.get('bus') if target_elem is not None else 'N/A'

                            disks.append({'path': disk_path, 'status': 'disabled', 'cache_mode': cache_mode, 'discard_mode': discard_mode, 'bus': bus})
    except ET.ParseError:
        pass  # Failed to get disks, continue without them

    return disks

def get_all_vm_disk_usage(conn: libvirt.virConnect) -> dict[str, list[str]]:
    """
    Scans all VMs and returns a mapping of disk path to a list of VM names.
    """
    disk_to_vms_map = {}
    if not conn:
        return disk_to_vms_map
    
    try:
        domains = conn.listAllDomains(0)
    except libvirt.libvirtError:
        return disk_to_vms_map

    for domain in domains:
        try:
            xml_desc = domain.XMLDesc(0)
            disks = get_vm_disks_info(conn, xml_desc) # Re-use existing function
            vm_name = domain.name()
            for disk in disks:
                path = disk.get('path')
                if path:
                    if path not in disk_to_vms_map:
                        disk_to_vms_map[path] = []
                    if vm_name not in disk_to_vms_map[path]:
                        disk_to_vms_map[path].append(vm_name)
        except libvirt.libvirtError:
            continue

    return disk_to_vms_map

def get_all_vm_nvram_usage(conn: libvirt.virConnect) -> dict[str, list[str]]:
    """
    Scans all VMs and returns a mapping of NVRAM file path to a list of VM names.
    """
    nvram_to_vms_map = {}
    if not conn:
        return nvram_to_vms_map

    try:
        domains = conn.listAllDomains(0)
    except libvirt.libvirtError:
        return nvram_to_vms_map

    for domain in domains:
        try:
            xml_desc = domain.XMLDesc(0)
            root = ET.fromstring(xml_desc)
            nvram_elem = root.find('.//os/nvram')
            if nvram_elem is not None:
                nvram_path = nvram_elem.text
                if nvram_path:
                    vm_name = domain.name()
                    if nvram_path not in nvram_to_vms_map:
                        nvram_to_vms_map[nvram_path] = []
                    if vm_name not in nvram_to_vms_map[nvram_path]:
                        nvram_to_vms_map[nvram_path].append(vm_name)
        except (libvirt.libvirtError, ET.ParseError):
            continue
    return nvram_to_vms_map


def get_supported_machine_types(conn, domain):
    """
    Returns a list of supported machine types for the domain's architecture.
    """
    if not conn or not domain:
        return []

    try:
        # Get domain architecture
        domain_xml = domain.XMLDesc(0)
        domain_root = ET.fromstring(domain_xml)
        arch_elem = domain_root.find(".//os/type")
        arch = arch_elem.get('arch') if arch_elem is not None else 'x86_64' # default

        # Get capabilities
        caps_xml = conn.getCapabilities()
        caps_root = ET.fromstring(caps_xml)

        # Find machines for that arch
        machines = [m.text for m in caps_root.findall(f".//guest/arch[@name='{arch}']/machine")]
        return sorted(list(set(machines)))
    except (libvirt.libvirtError, ET.ParseError) as e:
        print(f"Error getting machine types: {e}")
        return []


def get_vm_shared_memory_info(xml_content: str) -> bool:
    """Check if shared memory is enabled for the VM."""
    try:
        root = ET.fromstring(xml_content)
        memory_backing = root.find('memoryBacking')
        if memory_backing is not None:
            if memory_backing.find('shared') is not None:
                return True
            access_elem = memory_backing.find('access')
            if access_elem is not None and access_elem.get('mode') == 'shared':
                return True
    except (ET.ParseError, AttributeError):
        pass
    return False

def get_boot_info(xml_content: str, conn: libvirt.virConnect) -> dict:
    """Extracts boot information from the VM's XML."""
    root = ET.fromstring(xml_content)
    os_elem = root.find('.//os')
    if os_elem is None:
        return {'menu_enabled': False, 'order': []}

    boot_menu = os_elem.find('bootmenu')
    menu_enabled = boot_menu is not None and boot_menu.get('enable') == 'yes'

    # First, try to get boot order from devices
    devices = []
    # Find all devices with a <boot order='...'> element
    for dev_node in root.findall('.//devices/*[boot]'):
        boot_elem = dev_node.find('boot')
        order = boot_elem.get('order')
        if order:
            try:
                order = int(order)
                if dev_node.tag == 'disk':
                    source_elem = dev_node.find('source')
                    if source_elem is not None:
                        path = None
                        if "file" in source_elem.attrib:
                            path = source_elem.attrib["file"]
                        elif "dev" in source_elem.attrib:
                            path = source_elem.attrib["dev"]
                        elif "pool" in source_elem.attrib and "volume" in source_elem.attrib:
                            pool_name = source_elem.attrib["pool"]
                            vol_name = source_elem.attrib["volume"]
                            try:
                                pool = conn.storagePoolLookupByName(pool_name)
                                vol = pool.storageVolLookupByName(vol_name)
                                path = vol.path()
                            except libvirt.libvirtError:
                                pass # Could not resolve path
                        if path:
                            devices.append((order, path))

                elif dev_node.tag == 'interface':
                    mac_elem = dev_node.find('mac')
                    if mac_elem is not None:
                        devices.append((order, mac_elem.get('address')))
            except (ValueError, TypeError):
                continue

    # Sort devices by boot order
    devices.sort(key=lambda x: x[0])
    order_from_devices = [dev[1] for dev in devices]

    if order_from_devices:
        return {'menu_enabled': menu_enabled, 'order': order_from_devices}

    # Fallback to legacy <boot dev='...'>
    order_from_os = [boot.get('dev') for boot in os_elem.findall('boot')]

    return {'menu_enabled': menu_enabled, 'order': order_from_os}


def get_vm_video_model(xml_content: str) -> str | None:
    """Extracts the video model from a VM's XML definition."""
    try:
        root = ET.fromstring(xml_content)
        video = root.find('.//devices/video/model')
        if video is not None:
            return video.get('type')
    except ET.ParseError:
        pass
    return None

def get_vm_cpu_model(xml_content: str) -> str | None:
    """Extracts the cpu model from a VM's XML definition."""
    try:
        root = ET.fromstring(xml_content)
        cpu = root.find('.//cpu')
        if cpu is not None:
            return cpu.get('mode')
    except ET.ParseError:
        pass
    return None

def get_vm_sound_model(xml_content: str) -> str | None:
    """Extracts the sound model from a VM's XML definition."""
    try:
        root = ET.fromstring(xml_content)
        sound = root.find('.//devices/sound')
        if sound is not None:
            return sound.get("model")
    except ET.ParseError:
        pass
    return None

def get_vm_tpm_info(xml_content: str) -> list[dict]:
    """
    Extracts TPM information from a VM's XML definition.
    Returns a list of dictionaries with TPM details including passthrough devices.
    """
    tpm_info = []
    try:
        root = ET.fromstring(xml_content)
        devices = root.find("devices")

        if devices is not None:
            for tpm_elem in devices.findall("./tpm"):
                tpm_model = tpm_elem.get('model')

                backend_elem = tpm_elem.find('backend')
                tpm_type = 'emulated'  # Default
                device_path = ''
                backend_type = ''
                backend_path = ''

                if backend_elem is not None:
                    backend_type = backend_elem.get('type', '')
                    if backend_type == 'passthrough':
                        tpm_type = 'passthrough'
                        device_elem = backend_elem.find('device')
                        if device_elem is not None:
                            device_path = device_elem.get('path', '')
                    elif backend_type == 'emulator':
                        tpm_type = 'emulated'
                        # For emulator, backend_path might be in text if used as file (less common for default emulator)
                        backend_path = backend_elem.text if backend_elem.text else ''

                tpm_info.append({
                    'model': tpm_model,
                    'type': tpm_type,
                    'device_path': device_path,
                    'backend_type': backend_type,
                    'backend_path': backend_path
                })

    except ET.ParseError:
        pass

    return tpm_info

def get_vm_rng_info(xml_content: str) -> dict:
    """
    Extracts RNG (Random Number Generator) information from a VM's XML definition.
    Returns a dictionary with RNG details.
    """
    rng_info = {
        'rng_model': None,
        'backend_model': None,
        'backend_path': None,
    }
    try:
        root = ET.fromstring(xml_content)
        devices = root.find("devices")

        if devices is not None:
            rng_elem = devices.find("./rng")
            if rng_elem is not None:
                rng_info['rng_model'] = rng_elem.get('model')

                backend_elem = rng_elem.find('backend')
                if backend_elem is not None:
                    rng_info['backend_model'] = backend_elem.get('model')

                    if rng_info['backend_model'] == 'random':
                        rng_info['backend_path'] = backend_elem.text
                    else:
                        source_elem = backend_elem.find('source')
                        if source_elem is not None:
                            rng_info['backend_path'] = source_elem.get('path')

    except ET.ParseError:
        pass

    return rng_info

def get_vm_watchdog_info(xml_content: str) -> dict:
    """
    Extracts Watchdog information from a VM's XML definition.
    Returns a dictionary with Watchdog details.
    """
    watchdog_info = {
        'model': None,
        'action': None
    }

    try:
        root = ET.fromstring(xml_content)
        devices = root.find("devices")

        if devices is not None:
            watchdog_elem = devices.find("./watchdog")
            if watchdog_elem is not None:
                watchdog_info['model'] = watchdog_elem.get('model')
                watchdog_info['action'] = watchdog_elem.get('action')

    except ET.ParseError:
        pass

    return watchdog_info

def get_vm_input_info(xml_content: str) -> list[dict]:
    """
    Extracts Input (keyboard and mouse) information from a VM's XML definition.
    Returns a list of dictionaries with input device details.
    """
    input_info = []

    try:
        root = ET.fromstring(xml_content)
        devices = root.find("devices")

        if devices is not None:
            for input_elem in devices.findall("./input"):
                input_type = input_elem.get('type')
                input_bus = input_elem.get('bus')

                input_details = {
                    'type': input_type,
                    'bus': input_bus
                }

                # Add specific details for different input types
                if input_type == 'tablet':
                    tablet_elem = input_elem.find('tablet')
                    if tablet_elem is not None:
                        input_details['tablet'] = True
                elif input_type == 'mouse' or input_type == 'keyboard':
                    # Mouse and keyboard devices might have specific properties
                    pass  # Add more specific handling if needed

                input_info.append(input_details)

    except ET.ParseError:
        pass

    return input_info

def get_vm_graphics_info(xml_content: str) -> dict:
    """
    Extracts graphics information (VNC/Spice) from a VM's XML definition.
    Returns a dictionary with graphics details.
    """
    graphics_info = {
        'type': None,
        'listen_type': 'none',  # 'none' or 'address'
        'address': '0.0.0.0', # Default to all interfaces
        'port': None,
        'autoport': True,
        'password_enabled': False,
        'password': None,
    }

    try:
        root = ET.fromstring(xml_content)
        devices = root.find('devices')
        if devices is None:
            return graphics_info

        graphics_elem = devices.find('graphics')
        if graphics_elem is None:
            return graphics_info

        graphics_type = graphics_elem.get('type')
        if graphics_type not in ['vnc', 'spice']:
            return graphics_info

        graphics_info['type'] = graphics_type
        graphics_info['port'] = graphics_elem.get('port')
        graphics_info['autoport'] = graphics_elem.get('autoport') != 'no'

        listen_elem = graphics_elem.find('listen')
        if listen_elem is not None:
            listen_type = listen_elem.get('type')
            if listen_type in ['address', 'network']: # 'network' is deprecated but might be found
                graphics_info['listen_type'] = 'address'
                graphics_info['address'] = listen_elem.get('address', '0.0.0.0')
            else: # 'none' (default), 'socket' (not exposed in UI)
                graphics_info['listen_type'] = 'none'
                graphics_info['address'] = '' # Clear address if listen type is none

        if graphics_elem.get('passwd'):
            graphics_info['password_enabled'] = True
            graphics_info['password'] = graphics_elem.get('passwd') # Note: libvirt XML may not store password

    except ET.ParseError:
        pass

    return graphics_info

def check_for_spice_vms(conn):
    """
    Checks if any VM uses Spice graphics.
    Returns a message if a Spice VM is found, otherwise None.
    """
    if not conn:
        return None
    try:
        all_domains = conn.listAllDomains(0) or []
        for domain in all_domains:
            xml_content = domain.XMLDesc(0)
            graphics_info = get_vm_graphics_info(xml_content)
            if graphics_info.get("type") == "spice":
                return "Some VMs use Spice graphics. 'Web Console' is only available for VNC."
    except libvirt.libvirtError:
        pass
    return None

def get_all_network_usage(conn: libvirt.virConnect) -> dict[str, list[str]]:
    """
    Scans all VMs and returns a mapping of network name to a list of VM names using it.
    """
    network_to_vms = {}
    if not conn:
        return network_to_vms

    try:
        domains = conn.listAllDomains(0)
    except libvirt.libvirtError:
        return network_to_vms

    for domain in domains:
        try:
            xml_desc = domain.XMLDesc(0)
            vm_name = domain.name()
            # get_vm_networks_info is already in vm_queries.py
            networks = get_vm_networks_info(xml_desc)
            for net in networks:
                net_name = net.get('network')
                if net_name:
                    if net_name not in network_to_vms:
                        network_to_vms[net_name] = []
                    if vm_name not in network_to_vms[net_name]:
                        network_to_vms[net_name].append(vm_name)
        except libvirt.libvirtError:
            continue

    return network_to_vms


def get_attached_usb_devices(xml_content: str) -> list[dict]:
    """Gets all USB devices attached to the VM described by xml_content."""
    attached_devices = []
    try:
        root = ET.fromstring(xml_content)
        for hostdev in root.findall(".//devices/hostdev[@type='usb']"):
            source = hostdev.find('source')
            vendor = source.find('vendor')
            product = source.find('product')
            if vendor is not None and product is not None:
                vendor_id = vendor.get('id')
                product_id = product.get('id')
                attached_devices.append({
                    "vendor_id": vendor_id,
                    "product_id": product_id,
                })
    except ET.ParseError as e:
        logging.error(f"Error parsing XML for attached USB devices: {e}")
    except Exception as e:
        logging.error(f"Unexpected error getting attached USB devices: {e}")
    return attached_devices


def get_serial_devices(xml_content: str) -> list[dict]:
    """
    Extracts serial and console device information from a VM's XML definition.
    """
    devices = []
    try:
        root = ET.fromstring(xml_content)
        # Find serial devices
        for serial in root.findall(".//devices/serial"):
            dev_type = serial.get('type')
            target = serial.find('target')
            port = target.get('port') if target is not None else 'N/A'
            devices.append({
                'device': 'serial',
                'type': dev_type,
                'port': port,
                'details': f"Type: {dev_type}, Port: {port}"
            })
        # Find console devices
        for console in root.findall(".//devices/console"):
            dev_type = console.get('type')
            target = console.find('target')
            target_type = target.get('type') if target is not None else 'N/A'
            port = target.get('port') if target is not None else 'N/A'
            devices.append({
                'device': 'console',
                'type': dev_type,
                'port': port,
                'details': f"Type: {dev_type}, Target: {target_type} on port {port}"
            })
    except ET.ParseError as e:
        logging.error(f"Error parsing XML for serial devices: {e}")
    return devices

def get_attached_pci_devices(xml_content: str) -> list[dict]:
    """
    Parses the VM XML description and returns a list of attached PCI devices (hostdev).
    """
    attached_pci_devices = []
    try:
        root = ET.fromstring(xml_content)
        # Find all hostdev devices with a PCI address
        for hostdev_elem in root.findall(".//devices/hostdev[@type='pci']"):
            source_elem = hostdev_elem.find('source')
            if source_elem is not None:
                address_elem = source_elem.find('address')
                if address_elem is not None:
                    domain = address_elem.get('domain')
                    bus = address_elem.get('bus')
                    slot = address_elem.get('slot')
                    function = address_elem.get('function')
                    if all([domain, bus, slot, function]):
                        pci_address = f"{int(domain, 16):04x}:{int(bus, 16):02x}:{int(slot, 16):02x}.{int(function, 16):01x}"
                        attached_pci_devices.append({
                            'pci_address': pci_address,
                            'source_xml': ET.tostring(hostdev_elem, encoding='unicode')
                        })
    except ET.ParseError as e:
        logging.error(f"Error parsing XML for attached PCI devices: {e}")
    except Exception as e:
        logging.error(f"Unexpected error getting attached PCI devices: {e}")
    return attached_pci_devices
