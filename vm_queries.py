"""
Module for retrieving information about virtual machines.
"""
import xml.etree.ElementTree as ET
import libvirt
from libvirt_utils import _get_disabled_disks_elem, VMANAGER_NS
from utils import log_function_call


@log_function_call
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
                'detail_network': get_vm_network_ip(domain),
                'network_dns_gateway': get_vm_network_dns_gateway_info(domain),
                'disks': get_vm_disks_info(conn, xml_content),
                'devices': get_vm_devices_info(xml_content),
            }
            vm_info_list.append(vm_info)

    return vm_info_list

@log_function_call
def get_vm_network_dns_gateway_info(domain: str):
    """
    Extracts DNS and gateway information for networks connected to the VM.
    """
    pass

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

@log_function_call
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

        # We are interested in interfaces that are part of a network
        if network_name:
            networks.append({"mac": mac_address, "network": network_name})
    return networks


@log_function_call
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

@log_function_call
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


@log_function_call
def get_vm_disks_info(conn: libvirt.virConnect, xml_content: str) -> list[dict]:
    """
    Extracts disks info from a VM's XML definition.
    Returns a list of dictionaries with 'path' and 'status'.
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
                    disks.append({'path': disk_path, 'status': 'enabled'})

        # Disabled disks from metadata
        metadata_elem = root.find('metadata')
        if metadata_elem is not None:
            vmanager_meta_elem = metadata_elem.find(f'{{{VMANAGER_NS}}}vmanager')
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
                            disks.append({'path': disk_path, 'status': 'disabled'})
    except ET.ParseError:
        pass  # Failed to get disks, continue without them

    return disks

@log_function_call
def get_all_vm_disk_usage(conn: libvirt.virConnect) -> dict[str, str]:
    """
    Scans all VMs and returns a mapping of disk path to VM name.
    """
    disk_to_vm_map = {}
    if not conn:
        return disk_to_vm_map
    
    try:
        domains = conn.listAllDomains(0)
    except libvirt.libvirtError:
        return disk_to_vm_map

    for domain in domains:
        try:
            xml_desc = domain.XMLDesc(0)
            disks = get_vm_disks_info(conn, xml_desc) # Re-use existing function
            vm_name = domain.name()
            for disk in disks:
                path = disk.get('path')
                if path:
                    disk_to_vm_map[path] = vm_name
        except libvirt.libvirtError:
            continue
            
    return disk_to_vm_map

@log_function_call
def get_all_vm_nvram_usage(conn: libvirt.virConnect) -> dict[str, str]:
    """
    Scans all VMs and returns a mapping of NVRAM file path to VM name.
    """
    nvram_to_vm_map = {}
    if not conn:
        return nvram_to_vm_map

    try:
        domains = conn.listAllDomains(0)
    except libvirt.libvirtError:
        return nvram_to_vm_map

    for domain in domains:
        try:
            xml_desc = domain.XMLDesc(0)
            root = ET.fromstring(xml_desc)
            nvram_elem = root.find('.//os/nvram')
            if nvram_elem is not None:
                nvram_path = nvram_elem.text
                if nvram_path:
                    vm_name = domain.name()
                    nvram_to_vm_map[nvram_path] = vm_name
        except (libvirt.libvirtError, ET.ParseError):
            continue
    return nvram_to_vm_map


@log_function_call
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


@log_function_call
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

@log_function_call
def get_boot_info(xml_content: str) -> dict:
    """Extracts boot information from the VM's XML."""
    root = ET.fromstring(xml_content)
    os_elem = root.find('os')
    if os_elem is None:
        return {'menu_enabled': False, 'order': []}

    boot_menu = os_elem.find('bootmenu')
    menu_enabled = boot_menu is not None and boot_menu.get('enable') == 'yes'

    order = [boot.get('dev') for boot in os_elem.findall('boot')]

    return {'menu_enabled': menu_enabled, 'order': order}


@log_function_call
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

@log_function_call
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

@log_function_call
def get_vm_sound_model(xml_content: str) -> str | None:
    """Extracts the sound model from a VM's XML definition."""
    try:
        root = ET.fromstring(xml_content)
        devices = root.find("devices")
        if devices is not None:
            for sound_elem in devices.findall("sound"):
                model_elem = sound_elem.find("model")
                if model_elem is not None:
                    return model_elem.get("type")
    except ET.ParseError:
        pass
    return None

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

@log_function_call
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
