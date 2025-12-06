"""
lib to get all VM info
"""
import xml.etree.ElementTree as ET
import os
import libvirt
import string
import subprocess

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
                'detail_network': get_vm_network_ip(domain),
                'network_dns_gateway': get_vm_network_dns_gateway_info(domain),
                'disks': get_vm_disks_info(xml_content),
                'devices': get_vm_devices_info(xml_content),
            }
            vm_info_list.append(vm_info)

    return vm_info_list

def add_disk(domain, disk_path, device_type='disk', create=False, size_gb=10, disk_format='qcow2'):
    """
    Adds a disk to a VM. Can optionally create a new disk image.
    device_type can be 'disk' or 'cdrom'
    """
    if not domain:
        raise ValueError("Invalid domain object.")

    # Determine target device
    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)
    
    if device_type == 'disk':
        bus = 'virtio'
        prefix = 'vd'
        dev_letters = string.ascii_lowercase
    elif device_type == 'cdrom':
        bus = 'sata'
        prefix = 'sd'
        dev_letters = string.ascii_lowercase
    else:
        raise ValueError(f"Unsupported device type: {device_type}")

    used_devs = [
        target.get("dev")
        for target in root.findall(".//disk/target")
        if target.get("dev")
    ]
    
    target_dev = ""
    for letter in dev_letters:
        dev = f"{prefix}{letter}"
        if dev not in used_devs:
            target_dev = dev
            break
    
    if not target_dev:
        raise Exception("No available device slots for new disk.")

    if create:
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(disk_path), exist_ok=True)
            subprocess.run(['qemu-img', 'create', '-f', disk_format, disk_path, f'{size_gb}G'], check=True)
        except (subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
            raise Exception(f"Failed to create disk image: {e}")

    if device_type == 'disk':
        disk_xml = f"""
        <disk type='file' device='disk'>
            <driver name='qemu' type='{disk_format}'/>
            <source file='{disk_path}'/>
            <target dev='{target_dev}' bus='{bus}'/>
        </disk>
        """
    else: # cdrom
        disk_xml = f"""
        <disk type='file' device='cdrom'>
            <driver name='qemu' type='raw'/>
            <source file='{disk_path}'/>
            <target dev='{target_dev}' bus='{bus}'/>
            <readonly/>
        </disk>
        """

    flags = libvirt.VIR_DOMAIN_AFFECT_CONFIG
    if domain.isActive():
        flags |= libvirt.VIR_DOMAIN_AFFECT_LIVE
        
    domain.attachDeviceFlags(disk_xml, flags)
    return target_dev

def remove_disk(domain, disk_dev_path):
    """
    Removes a disk from a VM based on its device path (e.g. /path/to/disk.img) or device name (vda)
    """
    if not domain:
        raise ValueError("Invalid domain object.")

    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)
    
    disk_to_remove_xml = None
    for disk in root.findall(".//disk[@device='disk'] | .//disk[@device='cdrom']"):
        source = disk.find("source")
        target = disk.find("target")
        
        match = False
        if source is not None and source.get("file") == disk_dev_path:
            match = True
        elif target is not None and target.get("dev") == disk_dev_path:
            match = True

        if match:
            disk_to_remove_xml = ET.tostring(disk, encoding="unicode")
            break
            
    if not disk_to_remove_xml:
        raise Exception(f"Disk with device path or name '{disk_dev_path}' not found.")

    flags = libvirt.VIR_DOMAIN_AFFECT_CONFIG
    if domain.isActive():
        flags |= libvirt.VIR_DOMAIN_AFFECT_LIVE
        
    domain.detachDeviceFlags(disk_to_remove_xml, flags)


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

def get_vm_description(domain):
    """
    desc of the VM
    """
    try:
        return domain.metadata(libvirt.VIR_DOMAIN_METADATA_DESCRIPTION, None)
    except libvirt.libvirtError:
        return "No description available"

def get_vm_firmware_info(xml_content: str) -> str:
    """
    Extracts firmware (BIOS/UEFI) from a VM's XML definition.
    """
    firmware = "BIOS" # Default to BIOS

    try:
        root = ET.fromstring(xml_content)
        os_elem = root.find('os')

        # Determine firmware
        if os_elem is not None:
            loader_elem = os_elem.find('loader')
            if loader_elem is not None and loader_elem.get('type') == 'pflash':
                loader_path = loader_elem.text
                if loader_path:
                    firmware_basename = os.path.basename(loader_path)
                    firmware = f"UEFI {firmware_basename}"
            else:
                bootloader_elem = os_elem.find('bootloader')
                if bootloader_elem is not None:
                    firmware = "BIOS"

    except ET.ParseError:
        pass # Return default values if XML parsing fails

    return firmware

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

def get_vm_networks_info(xml_content: str) -> str:
    """
    Extracts network from a VM's XML definition.
    """
    networks = []
    try:
        root = ET.fromstring(xml_content)
        devices = root.find("devices")
        if devices is not None:
            interface_elements = devices.findall("interface")
            for interface in interface_elements:
                # Get interface type
                interface_type = interface.get("type", "unknown")
                # Get source (bridge, network, etc.)
                source = interface.find("source")
                if source is not None:
                    if interface_type == "bridge":
                        bridge_name = source.get("bridge", "unknown")
                        networks.append(f"bridge: {bridge_name}")
                    elif interface_type == "network":
                        network_name = source.get("network", "unknown")
                        networks.append(f"network: {network_name}")
                    elif interface_type == "user":
                        networks.append("user: network")
                else:
                    networks.append(f"{interface_type}: unknown")
    except:
        pass  # Failed to get networks, continue without them

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
    }

    try:
        root = ET.fromstring(xml_content)
        devices = root.find("devices")

        if devices is not None:
            # virtiofs
            for fs_elem in devices.findall("./filesystem[@type='mount'][@model='virtiofs']"):
                source = fs_elem.find('source')
                target = fs_elem.find('target')
                if source is not None and target is not None:
                    devices_info['virtiofs'].append({
                        'source': source.get('dir'),
                        'target': target.get('dir')
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

def get_vm_disks_info(xml_content: str) ->str:
    """
    Extracts disks info from a VM's XML definition.
    """
    disks = []
    try:

        root = ET.fromstring(xml_content)
        devices = root.find("devices")
        if devices is not None:
            disk_elements = devices.findall("disk")
            for disk in disk_elements:
                disk_source = disk.find("source")
                if disk_source is not None and "file" in disk_source.attrib:
                    disks.append(disk_source.attrib["file"])
                elif disk_source is not None and "dev" in disk_source.attrib:
                    disks.append(disk_source.attrib["dev"])
    except:
        pass  # Failed to get disks, continue without them

    return disks

def set_vcpu(domain, vcpu_count: int):
    """
    Sets the number of virtual CPUs for a VM.
    """
    if not domain:
        raise ValueError("Invalid domain object.")
    
    flags = libvirt.VIR_DOMAIN_AFFECT_CONFIG
    if domain.isActive():
        flags |= libvirt.VIR_DOMAIN_AFFECT_LIVE
        
    domain.setVcpusFlags(vcpu_count, flags)

def set_memory(domain, memory_mb: int):
    """
    Sets the memory for a VM in megabytes.
    """
    if not domain:
        raise ValueError("Invalid domain object.")
        
    memory_kb = memory_mb * 1024
    
    flags = libvirt.VIR_DOMAIN_AFFECT_CONFIG
    if domain.isActive():
        flags |= libvirt.VIR_DOMAIN_AFFECT_LIVE

    domain.setMemoryFlags(memory_kb, flags)

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

def set_machine_type(domain, new_machine_type):
    """
    Sets the machine type for a VM.
    The VM must be stopped.
    """
    if not domain:
        raise ValueError("Invalid domain object.")
        
    if domain.isActive():
        raise libvirt.libvirtError("VM must be stopped to change machine type.")
        
    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)
    
    type_elem = root.find(".//os/type")
    if type_elem is None:
        raise Exception("Could not find OS type element in VM XML.")
        
    type_elem.set('machine', new_machine_type)
    
    new_xml_desc = ET.tostring(root, encoding='unicode')
    
    conn = domain.connect()
    conn.defineXML(new_xml_desc)

def list_networks(conn):
    """
    Lists all networks.
    """
    if not conn:
        return []

    networks = []
    for net in conn.listAllNetworks():
        xml_desc = net.XMLDesc(0)
        root = ET.fromstring(xml_desc)
        
        forward_elem = root.find('forward')
        mode = forward_elem.get('mode') if forward_elem is not None else 'isolated'
        
        networks.append({
            'name': net.name(),
            'mode': mode,
            'active': net.isActive(),
        })
    return networks

def create_nat_network(conn, name, forward_dev, ip_network, dhcp_enabled, dhcp_start, dhcp_end, domain_name):
    """
    Creates a new NAT network.
    """
    if not conn:
        raise ValueError("Invalid libvirt connection.")

    import ipaddress
    net = ipaddress.ip_network(ip_network)

    xml = f"""
<network>
  <name>{name}</name>
  <forward mode='nat'>
    <nat>
      <port start='1024' end='65535'/>
    </nat>
  </forward>
  <bridge name='{name}' stp='on' delay='0'/>
  <mac address='52:54:00:..:..:..'/>
  <domain name='{domain_name}'/>
  <ip address='{net.network_address + 1}' netmask='{net.netmask}'>
"""
    if dhcp_enabled:
        xml += f"""
    <dhcp>
      <range start='{dhcp_start}' end='{dhcp_end}'/>
    </dhcp>
"""
    xml += """
  </ip>
</network>
"""

    net = conn.networkDefineXML(xml)
    net.create()
    net.setAutostart(True)
