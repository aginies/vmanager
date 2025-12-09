"""
lib to get all VM info
"""
import xml.etree.ElementTree as ET
import os
import secrets
import subprocess
import shlex
import uuid
import string
import libvirt

def _find_vol_by_path(conn, vol_path):
    """Finds a storage volume by its path and returns the volume and its pool."""
    # Slower but more compatible way to find a volume by path
    try:
        all_pool_names = conn.listStoragePools() + conn.listDefinedStoragePools()
    except libvirt.libvirtError:
        all_pool_names = []

    for pool_name in all_pool_names:
        try:
            pool = conn.storagePoolLookupByName(pool_name)
            if not pool.isActive():
                try:
                    pool.create(0)
                except libvirt.libvirtError:
                    continue  # Skip pools we can't start

            # listAllVolumes returns a list of virStorageVol objects
            for vol in pool.listAllVolumes():
                if vol and vol.path() == vol_path:
                    return vol, pool
        except libvirt.libvirtError:
            continue # Permissions issue or other problem, try next pool
    return None, None


def clone_vm(original_vm, new_vm_name):
    """
    Clones a VM, including its storage using libvirt's storage pool API.
    """
    conn = original_vm.connect()
    original_xml = original_vm.XMLDesc(0)
    root = ET.fromstring(original_xml)

    name_elem = root.find('name')
    if name_elem is not None:
        name_elem.text = new_vm_name

    uuid_elem = root.find('uuid')
    if uuid_elem is not None:
        uuid_elem.text = str(uuid.uuid4())

    for interface in root.findall('.//devices/interface'):
        mac_elem = interface.find('mac')
        if mac_elem is not None:
            interface.remove(mac_elem)

    for disk in root.findall('.//devices/disk'):
        if disk.get('device') != 'disk':
            continue

        source_elem = disk.find('source')
        if source_elem is None:
            continue

        original_disk_path = source_elem.get('file')
        if not original_disk_path:
            continue

        original_vol, original_pool = _find_vol_by_path(conn, original_disk_path)
        if not original_vol:
            raise Exception(f"Disk '{original_disk_path}' is not a managed libvirt storage volume. Cannot clone via API.")

        original_vol_xml = original_vol.XMLDesc(0)
        vol_root = ET.fromstring(original_vol_xml)

        _, vol_name_ext = os.path.splitext(original_vol.name())
        new_vol_name = f"{new_vm_name}_{secrets.token_hex(4)}{vol_name_ext}"
        vol_root.find('name').text = new_vol_name

        # Libvirt will handle capacity, allocation, and backing store when cloning.
        # Clear old path/key info just in case.
        if vol_root.find('key') is not None:
             vol_root.remove(vol_root.find('key'))
        target_elem = vol_root.find('target')
        if target_elem is not None:
            if target_elem.find('path') is not None:
                target_elem.remove(target_elem.find('path'))

        new_vol_xml = ET.tostring(vol_root, encoding='unicode')

        # Clone the volume. Use REFLINK for efficiency (thin clone).
        try:
            new_vol = original_pool.createXMLFrom(new_vol_xml, original_vol, libvirt.VIR_STORAGE_VOL_CREATE_REFLINK)
        except libvirt.libvirtError as e:
            # If reflinking is not supported by the storage backend, fall back to a full clone.
            if 'unsupported flags' in str(e).lower():
                new_vol = original_pool.createXMLFrom(new_vol_xml, original_vol, 0)
            else:
                raise

        disk.set('type', 'volume')
        if 'file' in source_elem.attrib:
            del source_elem.attrib['file']
        source_elem.set('pool', original_pool.name())
        source_elem.set('volume', new_vol.name())

    new_xml = ET.tostring(root, encoding='unicode')
    new_vm = conn.defineXML(new_xml)

    return new_vm

def rename_vm(domain, new_name, delete_snapshots=False):
    """
    Renames a VM.
    The VM must be stopped.
    If delete_snapshots is True, it will delete all snapshots before renaming.
    """
    if not domain:
        raise ValueError("Invalid domain object.")

    if domain.isActive():
        raise libvirt.libvirtError("VM must be stopped to be renamed.")

    conn = domain.connect()

    if domain.name() == new_name:
        return  # It's already named this, do nothing.

    # Check for snapshots
    num_snapshots = domain.snapshotNum(0)
    if num_snapshots > 0:
        if delete_snapshots:
            for snapshot in domain.listAllSnapshots(0):
                snapshot.delete(0)
        else:
            raise libvirt.libvirtError(f"Cannot rename VM with {num_snapshots} snapshot(s).")

    # Check if a VM with the new name already exists
    try:
        conn.lookupByName(new_name)
        # If lookup succeeds, a VM with the new name already exists.
        raise libvirt.libvirtError(f"A VM with the name '{new_name}' already exists.")
    except libvirt.libvirtError as e:
        # "domain not found" is the expected error if the name is available.
        # We check the error code to be sure, as the error message string
        if e.get_error_code() != libvirt.VIR_ERR_NO_DOMAIN:
            raise # Re-raise other libvirt errors.

    xml_desc = domain.XMLDesc(0)

    domain.undefine()

    try:
        # Modify XML with new name
        root = ET.fromstring(xml_desc)
        name_elem = root.find('name')
        if name_elem is None:
            raise Exception("Could not find name element in VM XML.")
        name_elem.text = new_name
        new_xml = ET.tostring(root, encoding='unicode')

        # Define the new domain from the modified XML
        conn.defineXML(new_xml)
    except Exception as e:
        conn.defineXML(xml_desc)
        raise Exception(f"Failed to rename VM, but restored original state. Error: {e}")

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

def remove_virtiofs(domain: libvirt.virDomain, target_dir: str):
    """
    Removes a virtiofs filesystem from a VM.
    The VM must be stopped to remove a virtiofs device.
    """
    if not domain:
        raise ValueError("Invalid domain object.")

    if domain.isActive():
        raise libvirt.libvirtError("VM must be stopped to remove a virtiofs device.")

    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)

    devices = root.find('devices')
    if devices is None:
        raise ValueError("Could not find <devices> in VM XML.")

    virtiofs_to_remove = None
    for fs_elem in devices.findall("./filesystem[@type='mount']"):
        driver = fs_elem.find('driver')
        target = fs_elem.find('target')
        if driver is not None and driver.get('type') == 'virtiofs' and target is not None:
            if target.get('dir') == target_dir:
                virtiofs_to_remove = fs_elem
                break

    if virtiofs_to_remove is None:
        raise ValueError(f"VirtIO-FS mount with target directory '{target_dir}' not found.")

    devices.remove(virtiofs_to_remove)

    new_xml = ET.tostring(root, encoding='unicode')

    conn = domain.connect()
    conn.defineXML(new_xml)

def add_virtiofs(domain: libvirt.virDomain, source_path: str, target_path: str, readonly: bool):
    """
    Adds a virtiofs filesystem to a VM.
    The VM must be stopped to add a virtiofs device.
    """
    if not domain:
        raise ValueError("Invalid domain object.")

    if domain.isActive():
        raise libvirt.libvirtError("VM must be stopped to add a virtiofs device.")

    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)

    devices = root.find('devices')
    if devices is None:
        devices = ET.SubElement(root, 'devices')

    # Create the new virtiofs XML element
    fs_elem = ET.SubElement(devices, "filesystem", type="mount", accessmode="passthrough")

    driver_elem = ET.SubElement(fs_elem, "driver", type="virtiofs")
    source_elem = ET.SubElement(fs_elem, "source", dir=source_path)
    target_elem = ET.SubElement(fs_elem, "target", dir=target_path)

    if readonly:
        ET.SubElement(fs_elem, "readonly")

    # Redefine the VM with the updated XML
    new_xml = ET.tostring(root, encoding='unicode')

    conn = domain.connect()
    conn.defineXML(new_xml)


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


def change_vm_network(domain: libvirt.virDomain, mac_address: str, new_network: str):
    """Changes the network for a VM's network interface."""
    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)

    interface_to_update = None
    for iface in root.findall(f".//devices/interface"):
        mac_node = iface.find("mac")
        if mac_node is not None and mac_node.get("address") == mac_address:
            interface_to_update = iface
            break

    if interface_to_update is None:
        raise ValueError(f"Interface with MAC {mac_address} not found.")

    source_node = interface_to_update.find("source")
    if source_node is None:
        raise ValueError("Interface does not have a source element.")

    # Check if network is already the same
    if source_node.get("network") == new_network:
        return # Nothing to do

    source_node.set("network", new_network)
    interface_xml = ET.tostring(interface_to_update, 'unicode')

    state = domain.info()[0]
    flags = libvirt.VIR_DOMAIN_DEVICE_MODIFY_CONFIG
    if state in [libvirt.VIR_DOMAIN_RUNNING, libvirt.VIR_DOMAIN_PAUSED]:
        flags |= libvirt.VIR_DOMAIN_DEVICE_MODIFY_LIVE

    domain.updateDeviceFlags(interface_xml, flags)

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

VMANAGER_NS = "http://github.com/aginies/vmanager"
ET.register_namespace("vmanager", VMANAGER_NS)

def _get_vmanager_metadata(root):
    metadata_elem = root.find('metadata')
    if metadata_elem is None:
        metadata_elem = ET.SubElement(root, 'metadata')

    vmanager_meta_elem = metadata_elem.find(f'{{{VMANAGER_NS}}}vmanager')
    if vmanager_meta_elem is None:
        vmanager_meta_elem = ET.SubElement(metadata_elem, f'{{{VMANAGER_NS}}}vmanager')

    return vmanager_meta_elem

def _get_disabled_disks_elem(root):
    vmanager_meta_elem = _get_vmanager_metadata(root)
    disabled_disks_elem = vmanager_meta_elem.find(f'{{{VMANAGER_NS}}}disabled-disks')
    if disabled_disks_elem is None:
        disabled_disks_elem = ET.SubElement(vmanager_meta_elem, f'{{{VMANAGER_NS}}}disabled-disks')
    return disabled_disks_elem

def get_vm_disks_info(xml_content: str) -> list[dict]:
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
                if disk_source is not None and "file" in disk_source.attrib:
                    disk_path = disk_source.attrib["file"]
                elif disk_source is not None and "dev" in disk_source.attrib:
                    disk_path = disk_source.attrib["dev"]

                if disk_path:
                    disks.append({'path': disk_path, 'status': 'enabled'})

        # Disabled disks from metadata
        metadata_elem = root.find('metadata')
        if metadata_elem is not None:
            vmanager_meta_elem = metadata_elem.find(f'{{{VMANAGER_NS}}}vmanager')
            if vmanager_meta_elem is not None:
                disabled_disks_elem = vmanager_meta_elem.find(f'{{{VMANAGER_NS}}}disabled-disks')
                if disabled_disks_elem is not None:
                    for disk in disabled_disks_elem.findall('disk'):
                        disk_path = ""
                        disk_source = disk.find("source")
                        if disk_source is not None and "file" in disk_source.attrib:
                            disk_path = disk_source.attrib["file"]
                        elif disk_source is not None and "dev" in disk_source.attrib:
                            disk_path = disk_source.attrib["dev"]

                        if disk_path:
                            disks.append({'path': disk_path, 'status': 'disabled'})
    except ET.ParseError:
        pass  # Failed to get disks, continue without them

    return disks

def disable_disk(domain, disk_path):
    """Disables a disk by moving it to a metadata section in the XML."""
    if domain.isActive():
        raise libvirt.libvirtError("VM must be stopped to disable a disk.")

    conn = domain.connect()
    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)

    devices = root.find('devices')
    if devices is None:
        raise ValueError("Could not find <devices> in VM XML.")

    disk_to_disable = None
    for disk in devices.findall('disk'):
        source = disk.find('source')
        path = None
        if source is not None and 'file' in source.attrib:
            path = source.attrib['file']
        elif source is not None and 'dev' in source.attrib:
            path = source.attrib['dev']

        if path == disk_path:
            disk_to_disable = disk
            break

    if disk_to_disable is None:
        raise ValueError(f"Enabled disk '{disk_path}' not found.")

    devices.remove(disk_to_disable)

    disabled_disks_elem = _get_disabled_disks_elem(root)
    disabled_disks_elem.append(disk_to_disable)

    new_xml = ET.tostring(root, encoding='unicode')
    conn.defineXML(new_xml)

def enable_disk(domain, disk_path):
    """Enables a disk by moving it from metadata back to devices."""
    if domain.isActive():
        raise libvirt.libvirtError("VM must be stopped to enable a disk.")

    conn = domain.connect()
    xml_desc = domain.XMLDesc(0)
    root = ET.fromstring(xml_desc)

    disabled_disks_elem = _get_disabled_disks_elem(root)

    disk_to_enable = None
    for disk in disabled_disks_elem.findall('disk'):
        source = disk.find('source')
        path = None
        if source is not None and 'file' in source.attrib:
            path = source.attrib['file']
        elif source is not None and 'dev' in source.attrib:
            path = source.attrib['dev']

        if path == disk_path:
            disk_to_enable = disk
            break

    if disk_to_enable is None:
        raise ValueError(f"Disabled disk '{disk_path}' not found.")

    disabled_disks_elem.remove(disk_to_enable)

    devices = root.find('devices')
    if devices is None:
        devices = ET.SubElement(root, 'devices')
    devices.append(disk_to_enable)

    new_xml = ET.tostring(root, encoding='unicode')
    conn.defineXML(new_xml)

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

def set_shared_memory(domain: libvirt.virDomain, enable: bool):
    """Enable or disable shared memory for a VM."""
    if domain.isActive():
        raise ValueError("Cannot change shared memory setting on a running VM.")

    xml_content = domain.XMLDesc(0)
    root = ET.fromstring(xml_content)

    memory_backing = root.find('memoryBacking')

    if enable:
        if memory_backing is None:
            memory_backing = ET.SubElement(root, 'memoryBacking')
        if memory_backing.find('shared') is None:
            ET.SubElement(memory_backing, 'shared')
    else:  # disable
        if memory_backing is not None:
            shared = memory_backing.find('shared')
            if shared is not None:
                memory_backing.remove(shared)

            access_elem = memory_backing.find('access')
            if access_elem is not None and access_elem.get('mode') == 'shared':
                memory_backing.remove(access_elem)

            # If memoryBacking is now empty, and has no attributes, remove it.
            if not list(memory_backing) and not memory_backing.attrib:
                root.remove(memory_backing)

    new_xml = ET.tostring(root, encoding='unicode')

    conn = domain.connect()
    conn.defineXML(new_xml)

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
            'autostart': net.autostart(),
        })
    return networks

def create_network(conn, name, typenet, forward_dev, ip_network, dhcp_enabled, dhcp_start, dhcp_end, domain_name):
    """
    Creates a new NAT/Routed network.
    """
    if not conn:
        raise ValueError("Invalid libvirt connection.")

    import ipaddress
    net = ipaddress.ip_network(ip_network)
    generated_mac = generate_mac_address()

    nat_xml = ""
    if typenet == "nat":
        nat_xml = """
    <nat>
      <port start='1024' end='65535'/>
    </nat>"""
    xml_forward_dev = ""
    if forward_dev:
        xml_forward_dev = f"dev='{forward_dev}'"

    xml = f"""
<network>
  <name>{name}</name>
  <forward mode='{typenet}' {xml_forward_dev}>{nat_xml}
  </forward>
  <bridge name='{name}' stp='on' delay='0'/>
  <mac address='{generated_mac}'/>
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

def delete_network(conn, network_name):
    """
    Deletes a network.
    """
    if not conn:
        raise ValueError("Invalid libvirt connection.")

    try:
        net = conn.networkLookupByName(network_name)
        if net.isActive():
            net.destroy()
        net.undefine()
    except libvirt.libvirtError as e:
        raise Exception(f"Error deleting network '{network_name}': {e}")


def get_vms_using_network(conn, network_name):
    """
    Get a list of VMs using a specific network.
    """
    if not conn:
        return []

    vm_names = []
    domains = conn.listAllDomains(0)
    if domains:
        for domain in domains:
            xml_desc = domain.XMLDesc(0)
            root = ET.fromstring(xml_desc)
            for iface in root.findall(".//devices/interface[@type='network']"):
                source = iface.find("source")
                if source is not None and source.get("network") == network_name:
                    vm_names.append(domain.name())
                    break
    return vm_names

def set_network_active(conn, network_name, active):
    """
    Sets a network to active or inactive.
    """
    if not conn:
        raise ValueError("Invalid libvirt connection.")
    try:
        net = conn.networkLookupByName(network_name)
        if active:
            net.create()
        else:
            net.destroy()
    except libvirt.libvirtError as e:
        raise Exception(f"Error setting network active status: {e}")

def set_network_autostart(conn, network_name, autostart):
    """
    Sets a network to autostart or not.
    """
    if not conn:
        raise ValueError("Invalid libvirt connection.")
    try:
        net = conn.networkLookupByName(network_name)
        net.setAutostart(autostart)
    except libvirt.libvirtError as e:
        raise Exception(f"Error setting network autostart status: {e}")


def get_host_network_interfaces():
    """
    Retrieves a list of network interface names and their primary IPv4 addresses available on the host.
    Returns a list of tuples: (interface_name, ip_address)
    """
    try:
        result = subprocess.run(
            ['ip', '-o', 'link', 'show'],
            capture_output=True,
            text=True,
            check=True
        )
        interfaces = []
        for line in result.stdout.splitlines():
            parts = line.split(': ')
            if len(parts) > 1:
                interface_name = parts[1].split('@')[0]
                if interface_name != 'lo':
                    ip_address = ""
                    # Get IPv4 address for the interface
                    ip_result = subprocess.run(
                        ['ip', '-o', '-4', 'addr', 'show', interface_name],
                        capture_output=True,
                        text=True,
                        check=False # Do not raise error if interface has no IP
                    )
                    if ip_result.returncode == 0:
                        ip_parts = ip_result.stdout.split()
                        if len(ip_parts) > 3:
                            ip_address = ip_parts[3].split('/')[0] # Extract IP before the /

                    interfaces.append((interface_name, ip_address))
        return interfaces
    except subprocess.CalledProcessError as e:
        print(f"Error getting network interfaces: {e}")
        return []
    except FileNotFoundError:
        print("Error: 'ip' command not found. Please ensure iproute2 is installed.")
        return []

def generate_mac_address():
    """Generates a random MAC address."""
    mac = [ 0x52, 0x54, 0x00,
            secrets.randbelow(0x7f),
            secrets.randbelow(0xff),
            secrets.randbelow(0xff) ]
    return ':'.join(map(lambda x: "%02x" % x, mac))
