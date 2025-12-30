"""
Utility functions for libvirt XML parsing and common helpers.
"""
import xml.etree.ElementTree as ET
import logging
import libvirt

VIRTUI_MANAGER_NS = "http://github.com/aginies/virtui-manager"
ET.register_namespace("virtui-manager", VIRTUI_MANAGER_NS)

def _find_vol_by_path(conn: libvirt.virConnect, vol_path):
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

def _get_vmanager_metadata(root):
    metadata_elem = root.find('metadata')
    if metadata_elem is None:
        metadata_elem = ET.SubElement(root, 'metadata')

    vmanager_meta_elem = metadata_elem.find(f'{{{VIRTUI_MANAGER_NS}}}virtuimanager')
    if vmanager_meta_elem is None:
        vmanager_meta_elem = ET.SubElement(metadata_elem, f'{{{VIRTUI_MANAGER_NS}}}virtuimanager')

    return vmanager_meta_elem

def _get_disabled_disks_elem(root):
    vmanager_meta_elem = _get_vmanager_metadata(root)
    disabled_disks_elem = vmanager_meta_elem.find(f'{{{VIRTUI_MANAGER_NS}}}disabled-disks')
    if disabled_disks_elem is None:
        disabled_disks_elem = ET.SubElement(vmanager_meta_elem, f'{{{VIRTUI_MANAGER_NS}}}disabled-disks')
    return disabled_disks_elem

def _find_pool_by_path(conn: libvirt.virConnect, file_path: str):
    """
    Finds an active storage pool that contains or manages the given file path.
    """
    for pool_name in conn.listStoragePools():
        try:
            pool = conn.storagePoolLookupByName(pool_name)
            if not pool.isActive():
                continue
            pool_info = ET.fromstring(pool.XMLDesc(0))
            source_path = pool_info.findtext("source/directory") or pool_info.findtext("target/path")
            if source_path and file_path.startswith(source_path):
                return pool
        except libvirt.libvirtError:
            continue
    return None

def get_cpu_models(conn: libvirt.virConnect, arch: str):
    """
    Get a list of CPU models for a given architecture.
    """
    if not conn:
        return []
    try:
        # Returns a list of supported CPU model names
        models = conn.getCPUModelNames(arch)
        return models
    except libvirt.libvirtError as e:
        print(f"Error getting CPU models for arch {arch}: {e}")
        return []

def find_all_vm(conn: libvirt.virConnect):
    """
    Find all VM from the current Hypervisor
    """
    allvm_list = []
    # Store all VM from the hypervisor
    domains = conn.listAllDomains(0)
    for domain in domains:
        if domain.name():
            vmdomain = domain.name()
            allvm_list.append(vmdomain)
    return allvm_list

def get_domain_capabilities_xml(
    conn: libvirt.virConnect,
    emulatorbin: str,
    arch: str,
    machine: str,
    flags: int = 0
) -> str | None:
    """
    Retrieves the domain capabilities XML for a specific guest configuration.
    """
    try:
        caps_xml = conn.getDomainCapabilities(
            emulatorbin=emulatorbin,
            arch=arch,
            machine=machine,
            flags=flags
        )
        return caps_xml
    except libvirt.libvirtError as e:
        logging.error(f"Error getting domain capabilities: {e}")
        return None

def get_video_domain_capabilities(xml_content: str) -> dict:
    """
    Parses the domain capabilities XML to extract supported video
    """
    supported_models = {
        'video_models': [],
    }

    if not xml_content:
        return supported_models

    try:
        root = ET.fromstring(xml_content)

        # Extract supported video models
        for video_elem in root.findall(".//video[@supported='yes']/enum[@name='modelType']"):
            for value_elem in video_elem.findall('value'):
                if value_elem.text:
                    supported_models['video_models'].append(value_elem.text)

    except ET.ParseError as e:
        logging.error(f"Error parsing domain capabilities XML: {e}")
    except Exception as e:
        logging.error(f"An unexpected error occurred during XML parsing: {e}")

    return supported_models

def get_sound_domain_capabilities(xml_content: str) -> dict:
    """
    Parses the domain capabilities XML to extract supported sound models.
    """
    supported_models = {
        'sound_models': [],
    }

    if not xml_content:
        return supported_models

    try:
        root = ET.fromstring(xml_content)

        # Extract supported sound models
        for sound_elem in root.findall(".//sound[@supported='yes']/enum[@name='model']"):
            for value_elem in sound_elem.findall('value'):
                if value_elem.text:
                    supported_models['sound_models'].append(value_elem.text)

    except ET.ParseError as e:
        logging.error(f"Error parsing domain capabilities XML: {e}")
    except Exception as e:
        logging.error(f"An unexpected error occurred during XML parsing: {e}")

    return supported_models

def _get_vm_names_from_uuids(conn: libvirt.virConnect, vm_uuids: list[str]) -> list[str]:
    """
    Get VM name from their vm_uuids
    """
    vm_names = []
    for uuid in vm_uuids:
        try:
            domain = conn.lookupByUUIDString(uuid)
            vm_names.append(domain.name())
        except libvirt.libvirtError:
            pass
    return vm_names

def get_network_info(conn: libvirt.virConnect, network_name: str) -> dict:
    """
    Get detailed information about a specific network based on its name.
    Extracts forward mode, port, bridge, network, and DHCP information.
    """
    try:
        network = conn.networkLookupByName(network_name)
        xml_desc = network.XMLDesc(0)
        root = ET.fromstring(xml_desc)

        info = {'name': network.name(), 'uuid': network.UUIDString()}

        # Forwarding info
        forward_elem = root.find('forward')
        if forward_elem is not None:
            info['forward_mode'] = forward_elem.get('mode')
            dev = forward_elem.get('dev')
            if dev is None:
                interface_elem = forward_elem.find('interface')
                if interface_elem is not None:
                    dev = interface_elem.get('dev')
            info['forward_dev'] = dev

            # NAT port range for forwarding
            nat_elem = forward_elem.find('nat')
            if nat_elem is not None:
                port_elem = nat_elem.find('port')
                if port_elem is not None:
                    info['port_forward_start'] = port_elem.get('start')
                    info['port_forward_end'] = port_elem.get('end')
        else:
            info['forward_mode'] = 'isolated' # If no forward element, it's an isolated network
            info['forward_dev'] = None

        # Bridge info
        bridge_elem = root.find('bridge')
        if bridge_elem is not None:
            info['bridge_name'] = bridge_elem.get('name')
        else:
            info['bridge_name'] = None

        # IP addressing info
        ip_elem = root.find('ip')
        if ip_elem is not None:
            info['ip_address'] = ip_elem.get('address')
            info['netmask'] = ip_elem.get('netmask')
            info['prefix'] = ip_elem.get('prefix')

            # DHCP info
            dhcp_elem = ip_elem.find('dhcp')
            if dhcp_elem is not None:
                info['dhcp'] = True
                range_elem = dhcp_elem.find('range')
                if range_elem is not None:
                    info['dhcp_start'] = range_elem.get('start')
                    info['dhcp_end'] = range_elem.get('end')
                else:
                    info['dhcp_start'] = None
                    info['dhcp_end'] = None
            else:
                info['dhcp'] = False
        else:
            info['ip_address'] = None
            info['netmask'] = None
            info['prefix'] = None
            info['dhcp'] = False

        # Domain name
        domain_elem = root.find('domain')
        if domain_elem is not None:
            info['domain_name'] = domain_elem.get('name')
        else:
            info['domain_name'] = None

        return info

    except libvirt.libvirtError:
        return {}


def get_host_usb_devices(conn: libvirt.virConnect) -> list[dict]:
    """Gets all USB devices from the host."""
    usb_devices = []
    try:
        devices = conn.listAllDevices(0)
        for dev in devices:
            try:
                xml_desc = dev.XMLDesc(0)
                root = ET.fromstring(xml_desc)
                if root.find("capability[@type='usb_device']") is not None:
                    capability = root.find("capability[@type='usb_device']")
                    vendor_elem = capability.find('vendor')
                    product_elem = capability.find('product')
                    vendor_id = vendor_elem.get('id') if vendor_elem is not None else None
                    product_id = product_elem.get('id') if product_elem is not None else None

                    if not vendor_id or not product_id:
                        continue

                    product_name = "Unknown"
                    if product_elem is not None and product_elem.text:
                        product_name = product_elem.text.strip()

                    vendor_name = "Unknown"
                    if vendor_elem is not None and vendor_elem.text:
                        vendor_name = vendor_elem.text.strip()

                    usb_devices.append({
                        "name": dev.name(),
                        "vendor_id": vendor_id,
                        "product_id": product_id,
                        "vendor_name": vendor_name,
                        "product_name": product_name,
                        "description": f"{vendor_name} - {product_name} ({vendor_id}:{product_id})"
                    })
            except libvirt.libvirtError as e:
                logging.warning(f"Skipping device {dev.name() if hasattr(dev, 'name') else 'unknown'}: {e}")
                continue
    except libvirt.libvirtError as e:
        logging.error(f"Error getting host USB devices: {e}")
    return usb_devices


def get_host_pci_devices(conn: libvirt.virConnect) -> list[dict]:
    """Gets all PCI devices from the host that are available for passthrough."""
    pci_devices = []
    try:
        devices = conn.listAllDevices(0)
        for dev in devices:
            try:
                xml_desc = dev.XMLDesc(0)
                root = ET.fromstring(xml_desc)
                if root.tag == 'capability' and root.get('type') == 'pci_device':
                    capability = root
                    vendor_elem = capability.find('vendor')
                    product_elem = capability.find('product')
                    address_elem = capability.find('address')

                    vendor_id = vendor_elem.get('id') if vendor_elem is not None else None
                    product_id = product_elem.get('id') if product_elem is not None else None

                    if not vendor_id or not product_id:
                        continue

                    product_name = "Unknown"
                    if product_elem is not None and product_elem.text:
                        product_name = product_elem.text.strip()

                    vendor_name = "Unknown"
                    if vendor_elem is not None and vendor_elem.text:
                        vendor_name = vendor_elem.text.strip()

                    pci_address = None
                    if address_elem is not None:
                        domain = address_elem.get('domain')
                        bus = address_elem.get('bus')
                        slot = address_elem.get('slot')
                        function = address_elem.get('function')
                        if all([domain, bus, slot, function]):
                            pci_address = f"{int(domain, 16):04x}:{int(bus, 16):02x}:{int(slot, 16):02x}.{int(function, 16)}"

                    pci_devices.append({
                        "name": dev.name(),
                        "vendor_id": vendor_id,
                        "product_id": product_id,
                        "vendor_name": vendor_name,
                        "product_name": product_name,
                        "pci_address": pci_address,
                        "description": f"{vendor_name} - {product_name} ({pci_address})" if pci_address else f"{vendor_name} - {product_name} ({vendor_id}:{product_id})"
                    })
            except (libvirt.libvirtError, ET.ParseError) as e:
                logging.warning(f"Skipping device {dev.name() if hasattr(dev, 'name') else 'unknown'}: {e}")
                continue
    except (libvirt.libvirtError, AttributeError) as e:
        logging.error(f"Error getting host PCI devices: {e}")
    return pci_devices
